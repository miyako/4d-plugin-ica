/*
 * Synthetic 4D engine boundary for ImageCaptureCore ownership regressions.
 *
 * Links the real plugin source (4DPlugin-ImageCaptureCore.cpp), the real
 * helper sources (4D Plugin API/Classes/*.cpp, support/4DPlugin-JSON.cpp)
 * and the bundled, unmodified 4D Plugin API (4DPluginAPI.c). Only gCall4D is
 * replaced: it models engine-side allocations (Unistrings, handles, pictures,
 * objects) with malloc/free so ASan reports double frees and use-after-free,
 * and keeps live sets so leaks are detected exactly.
 *
 * The ImageCaptureCore boundary is never entered: PluginMain(kInitPlugin)
 * is never called, so no ICDeviceBrowser is created and no camera or scanner
 * is enumerated, opened or scanned. Tests queue one synthetic scan result in
 * the plugin's callback queue (what the ICScannerDeviceDelegate methods push)
 * and dispatch it with the plugin's real listenerLoopExecuteMethod.
 *
 * Engine semantics modelled (SDK contract, 4DPluginAPI.c):
 *  - PA_CreateVariable(eVK_Unistring / eVK_Blob / eVK_Picture) allocates an
 *    empty string / PA_NewHandle(0) / empty picture; PA_SetStringVariable,
 *    PA_SetBlobVariable and PA_SetPictureVariable overwrite it shallowly.
 *    eVK_Object only zeroes the reference; eVK_Collection allocates nothing.
 *  - PA_ExecuteMethodByID / EXECUTE METHOD (1007) read their parameters; the
 *    caller keeps ownership and clears them afterwards.
 *  - PA_ExecuteMethodByID returns a caller-owned result (here: the callback
 *    method's text $0) to be cleared when the call succeeded; on error the
 *    result is not initialised (poisoned) and must not be cleared.
 *  - PA_GetObjectProperty returns an owned copy (poisoned on error);
 *    PA_SetObjectProperty deep-copies; PA_GetStringVariable borrows.
 *  - PA_SetStringInArray transfers the string to the array.
 */

#include "4DPluginAPI.h"
#include "PrivateTypes.h"
#include "EntryPoints.h"
#include "4DPlugin-ImageCaptureCore.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <map>
#include <set>
#include <string>
#include <vector>

void listenerLoopExecuteMethod();

namespace Scan {
    extern param_scan_context_info_t CALLBACK_METHOD_CONTEXT_INFO;
    extern C_TEXT LISTENER_METHOD;
    extern std::vector<param_scan_path_t> CALLBACK_PARAMS_SCAN_PATH;
    extern std::vector<param_scan_type_t> CALLBACK_PARAMS_SCAN_TYPE;
    extern std::vector<param_scan_data_t> CALLBACK_PARAMS_SCAN_DATA;
    extern std::vector<param_scan_info_t> CALLBACK_PARAMS_SCAN_INFO;
}

namespace {

typedef std::basic_string<PA_Unichar> u16;

u16 U(const char *s) { u16 r; while(*s) r.push_back((PA_Unichar)(unsigned char)*s++); return r; }

struct Obj { int rc; std::map<u16, PA_Variable> props; };

/* data must stay the first member: the SDK dereferences a handle as char** */
struct Handle { char *data; size_t size; };

std::set<void *> g_strings;
std::set<void *> g_pictures;
std::set<Obj *> g_objects;
std::set<void *> g_handles;

const PA_long32 kCallbackId = 4242;
const u16 kCallbackName = U("ICA_CALLBACK");
bool g_return_text = false;
bool g_fail_call = false;
bool g_fail_get = false;
void *g_returned = 0;

struct Call {
    int calls = 0; u16 method; PA_long32 type = -1; u16 path; std::string data; u16 ctx; u16 info;
};
Call g_byid, g_cmd;

PA_Unichar kPoisonBuf[] = { 'B', 'A', 'D', '!', 0 };
PA_Unichar *const kPoison = kPoisonBuf;

[[noreturn]] void die(const char *msg) {
    fprintf(stderr, "ENGINE VIOLATION: %s\n", msg);
    fflush(stderr);
    abort();
}

PA_Unistring new_string(const PA_Unichar *src, size_t len) {
    PA_Unichar *buf = (PA_Unichar *)malloc((len + 1) * sizeof(PA_Unichar));
    if(len) memcpy(buf, src, len * sizeof(PA_Unichar));
    buf[len] = 0;
    g_strings.insert(buf);
    PA_Unistring s;
    s.fLength = (PA_long32)len;
    s.fString = buf;
    s.fReserved1 = 0;
    s.fReserved2 = 0;
    return s;
}

void free_string(PA_Unistring *s) {
    if(!s->fString) return;
    if(s->fString == kPoison) die("cleared the result of a failed engine call");
    if(!g_strings.erase(s->fString)) die("disposed a string the engine does not own (double free?)");
    free(s->fString);
    s->fString = 0;
    s->fLength = 0;
}

void *new_picture() { void *p = malloc(16); g_pictures.insert(p); return p; }

void free_picture(void *p) {
    if(!p) return;
    if(!g_pictures.erase(p)) die("disposed a picture the engine does not own");
    free(p);
}

Handle *new_handle(size_t size) {
    Handle *h = (Handle *)malloc(sizeof(Handle));
    h->data = (char *)calloc(1, size ? size : 1);
    h->size = size;
    g_handles.insert(h);
    return h;
}

Handle *checked(void *p) {
    if(!g_handles.count(p)) die("used an unknown handle");
    return (Handle *)p;
}

void free_handle(Handle *h) {
    if(!h) return;
    if(!g_handles.erase(h)) die("disposed an unknown handle");
    free(h->data);
    free(h);
}

void release_object(Obj *o);

void clear_var(PA_Variable *v) {
    switch(v->fType) {
        case eVK_Unistring: free_string(&v->uValue.fString); break;
        case eVK_Blob: free_handle((Handle *)v->uValue.fBlob.fHandle); break;
        case eVK_Picture: free_picture(v->uValue.fPicture); break;
        case eVK_Object: if(v->uValue.fObject) release_object((Obj *)v->uValue.fObject); break;
        case eVK_Collection: if(v->uValue.fCollection) release_object((Obj *)v->uValue.fCollection); break;
        case eVK_ArrayUnicode: {
            Handle *h = (Handle *)v->uValue.fArray.fData;
            if(h) {
                PA_Unistring *items = (PA_Unistring *)checked(h)->data;
                for(PA_long32 i = 0; i <= v->uValue.fArray.fNbElements; i++) free_string(&items[i]);
                free_handle(h);
            }
            break;
        }
        default: break;
    }
    v->fType = eVK_Undefined;
}

PA_Variable copy_var(const PA_Variable &src) {
    PA_Variable dst = src;
    switch(src.fType) {
        case eVK_Unistring:
            dst.uValue.fString = new_string(src.uValue.fString.fString, src.uValue.fString.fLength);
            break;
        case eVK_Picture:
            dst.uValue.fPicture = new_picture();
            break;
        case eVK_Object:
        case eVK_Collection: {
            Obj *o = (Obj *)(src.fType == eVK_Object ? (void *)src.uValue.fObject : (void *)src.uValue.fCollection);
            if(o) { if(!g_objects.count(o)) die("copied a dead object"); o->rc++; }
            break;
        }
        default: break;
    }
    return dst;
}

Obj *new_object() { Obj *o = new Obj(); o->rc = 1; g_objects.insert(o); return o; }

void release_object(Obj *o) {
    if(!g_objects.count(o)) die("released a dead object (over-release?)");
    if(--o->rc == 0) {
        for(auto &kv : o->props) clear_var(&kv.second);
        g_objects.erase(o);
        delete o;
    }
}

u16 key_of(const PA_Unistring &k) { return u16(k.fString, k.fLength); }

u16 live_text(const PA_Variable &v, const char *what) {
    if(v.fType != eVK_Unistring) die(what);
    if(!g_strings.count(v.uValue.fString.fString)) die("engine received a string it does not own");
    return u16(v.uValue.fString.fString, v.uValue.fString.fLength);
}

/* params: type, path, data, ctx, info */
void record(Call &c, PA_Variable *const *p) {
    c.calls++;
    if(p[0]->fType != eVK_Longint) die("type parameter is not longint");
    c.type = p[0]->uValue.fLongint;
    c.path = live_text(*p[1], "path parameter is not text");
    if(p[2]->fType != eVK_Blob) die("data parameter is not a blob");
    Handle *h = (Handle *)p[2]->uValue.fBlob.fHandle;
    c.data = h ? std::string(checked(h)->data, (size_t)p[2]->uValue.fBlob.fSize) : std::string();
    c.ctx = live_text(*p[3], "context parameter is not text");
    c.info = live_text(*p[4], "info parameter is not text");
}

void engine(short selector, EngineBlock *eb) {
    switch(selector) {
        case EX_HANDLE_MANAGER: {
            Handle *h = (Handle *)eb->fHandle;
            switch(eb->fParam1) {
                case 1: eb->fHandle = (PA_Handle)new_handle((size_t)eb->fParam2); break;
                case 2: free_handle(checked(h)); break;
                case 3: {
                    checked(h);
                    size_t n = (size_t)eb->fParam2;
                    char *d = (char *)calloc(1, n ? n : 1);
                    memcpy(d, h->data, n < h->size ? n : h->size);
                    free(h->data);
                    h->data = d;
                    h->size = n;
                    break;
                }
                case 4: eb->fParam2 = (sLONG_PTR)checked(h)->size; break;
                case 5: eb->fParam3 = (sLONG_PTR)checked(h)->data; break;
                case 6: checked(h); break;
                default: die("unmodelled handle manager call");
            }
            eb->fError = 0;
            return;
        }
        case EX_CONVERT_STRING: {
            if(eb->fParam1 != 5) die("unmodelled string conversion");
            Handle *h = new_handle((size_t)eb->fParam4);
            if(eb->fParam4) memcpy(h->data, (const void *)eb->fParam3, (size_t)eb->fParam4);
            eb->fHandle = (PA_Handle)h;
            eb->fError = 0;
            return;
        }
        case EX_CREATE_UNISTRING: {
            const PA_Unichar *s = (const PA_Unichar *)eb->fHandle;
            size_t n = 0; while(s[n]) ++n;
            eb->fUniString1 = new_string(s, n);
            return;
        }
        case EX_DISPOSE_UNISTRING: free_string(&eb->fUniString1); return;
        case EX_VARIABLE_TO_STRING: {
            PA_Variable *v = (PA_Variable *)eb->fHandle;
            if(v->fType == eVK_Unistring) eb->fUniString1 = v->uValue.fString; /* borrowed */
            return;
        }
        case EX_CREATE_PICTURE: eb->fPicture = new_picture(); return;
        case EX_DISPOSE_PICTURE: free_picture(eb->fPicture); return;
        case EX_CLEAR_VARIABLE: clear_var((PA_Variable *)eb->fPtr1); eb->fError = 0; return;
        case EX_SET_OBJ_VALUE: {
            Obj *o = (Obj *)eb->fPtr1;
            if(!g_objects.count(o)) die("set on a dead object");
            u16 k = key_of(eb->fUniString1);
            auto it = o->props.find(k);
            if(it != o->props.end()) clear_var(&it->second);
            o->props[k] = copy_var(*(PA_Variable *)eb->fPtr2);
            return;
        }
        case EX_GET_OBJ_VALUE: {
            PA_Variable *out = (PA_Variable *)eb->fPtr2;
            memset(out, 0, sizeof(*out));
            if(g_fail_get) {
                out->fType = eVK_Unistring;
                out->uValue.fString.fString = kPoison;
                out->uValue.fString.fLength = 4;
                eb->fError = -1;
                return;
            }
            Obj *o = (Obj *)eb->fPtr1;
            if(!g_objects.count(o)) die("get on a dead object");
            auto it = o->props.find(key_of(eb->fUniString1));
            if(it == o->props.end()) out->fType = eVK_Undefined;
            else *out = copy_var(it->second);
            return;
        }
        case EX_GET_METHOD_ID:
            eb->fParam1 = (u16(eb->fUName) == kCallbackName) ? kCallbackId : 0;
            eb->fError = 0;
            return;
        case EX_CALL_BY_PROCID: {
            if(eb->fParam1 != kCallbackId || eb->fParam2 != 5) die("unexpected method call");
            PA_Variable *v = (PA_Variable *)checked(eb->fHandle)->data;
            PA_Variable *p[5] = { &v[1], &v[2], &v[3], &v[4], &v[5] };
            record(g_byid, p);
            if(g_fail_call) {
                v[0].fType = eVK_Unistring;
                v[0].uValue.fString.fString = kPoison;
                v[0].uValue.fString.fLength = 4;
                eb->fError = -1;
                return;
            }
            if(g_return_text) {
                v[0].fType = eVK_Unistring;
                v[0].uValue.fString = new_string(U("ok").c_str(), 2);
                g_returned = v[0].uValue.fString.fString;
            }
            eb->fError = 0;
            return;
        }
        case EX_EXECUTE_COMMAND_BY_ID: {
            PA_Variable **params = (PA_Variable **)eb->fPtr1;
            PA_Variable *ret = (PA_Variable *)eb->fPtr2;
            eb->fError = 0;
            switch(eb->fParam1) {
                case 1007: /* EXECUTE METHOD: no '*', so nothing is returned */
                    if(eb->fParam2 != 6) die("unexpected EXECUTE METHOD arity");
                    g_cmd.method = live_text(*params[0], "method name parameter is not text");
                    record(g_cmd, params + 1);
                    return;
                case 1231: { /* OB Is defined */
                    Obj *o = (Obj *)params[0]->uValue.fObject;
                    if(!g_objects.count(o)) die("OB Is defined on a dead object");
                    ret->fType = eVK_Boolean;
                    ret->uValue.fBoolean = o->props.count(key_of(params[1]->uValue.fString)) ? 1 : 0;
                    return;
                }
                case 1225: { /* OB Copy (PA_DuplicateObject) */
                    Obj *src = (Obj *)params[0]->uValue.fObject;
                    if(!g_objects.count(src)) die("OB Copy of a dead object");
                    Obj *o = new_object();
                    for(auto &kv : src->props) o->props[kv.first] = copy_var(kv.second);
                    ret->fType = eVK_Object;
                    ret->uValue.fObject = (PA_ObjectRef)o;
                    return;
                }
                case 1217: /* JSON Stringify */
                    if(!g_objects.count((Obj *)params[0]->uValue.fObject)) die("stringify of a dead object");
                    ret->fType = eVK_Unistring;
                    ret->uValue.fString = new_string(U("{}").c_str(), 2);
                    return;
                default: die("unexpected PA_ExecuteCommandByID");
            }
        }
        default: {
            char msg[64];
            snprintf(msg, sizeof msg, "unmodelled selector %d", (int)selector);
            die(msg);
        }
    }
}

void expect(bool ok, const char *what) {
    if(!ok) {
        fprintf(stderr, "FAIL: %s (live: strings %zu, handles %zu, pictures %zu, objects %zu)\n",
                what, g_strings.size(), g_handles.size(), g_pictures.size(), g_objects.size());
        exit(1);
    }
}

bool no_engine_allocations() {
    return g_strings.empty() && g_handles.empty() && g_pictures.empty() && g_objects.empty();
}

/* ---- ImageCaptureCore callback dispatch (LIVE) ---- */

const char kScanBytes[] = "PNG\x01\x02";
const char kScanPath[] = "/ica-synthetic/does-not-exist/scan.png";

void dispatch_one(const u16 &method, bool with_data = true) {
    Scan::LISTENER_METHOD.setUTF16String(method.c_str(), (uint32_t)method.size());
    Scan::CALLBACK_METHOD_CONTEXT_INFO = U("ctx-info");
    Scan::CALLBACK_PARAMS_SCAN_TYPE.push_back(with_data ? param_scan_type_data : param_scan_type_file);
    Scan::CALLBACK_PARAMS_SCAN_PATH.push_back(U(kScanPath));
    Scan::CALLBACK_PARAMS_SCAN_DATA.push_back(with_data
        ? param_scan_data_t(kScanBytes, kScanBytes + sizeof(kScanBytes) - 1) : param_scan_data_t());
    Scan::CALLBACK_PARAMS_SCAN_INFO.push_back(U("{\"page\":1}"));
    expect(no_engine_allocations(), "no engine allocations before dispatch");
    listenerLoopExecuteMethod();
    expect(Scan::CALLBACK_PARAMS_SCAN_TYPE.empty() && Scan::CALLBACK_PARAMS_SCAN_INFO.empty(),
           "dispatched scan removed from the queue");
}

void defect_byid_param_owner_leak() {
    dispatch_one(kCallbackName);
    expect(g_byid.calls == 1, "callback called once via PA_ExecuteMethodByID");
    expect(g_strings.empty(), "no engine strings leaked by the ByID callback parameters");
    expect(g_handles.empty(), "no blob handle leaked by the ByID callback parameters");
}

void defect_1007_param_owner_leak() {
    dispatch_one(U("ICA_UNRESOLVED"));
    expect(g_cmd.calls == 1, "callback called once via EXECUTE METHOD");
    expect(g_strings.empty(), "no engine strings leaked by the EXECUTE METHOD parameters");
    expect(g_handles.empty(), "no blob handle leaked by the EXECUTE METHOD parameters");
}

void defect_byid_result_not_cleared() {
    g_return_text = true;
    dispatch_one(kCallbackName);
    expect(g_byid.calls == 1, "callback called once");
    expect(g_returned != 0, "callback returned a text result");
    expect(!g_strings.count(g_returned), "callback result released");
}

void guard_byid_error_result_untouched() {
    g_fail_call = true;
    dispatch_one(kCallbackName);
    /* Clearing the poisoned result would abort with ENGINE VIOLATION. */
    expect(g_byid.calls == 1, "callback attempted once");
}

void control_byid_args_delivered() {
    dispatch_one(kCallbackName);
    expect(g_byid.calls == 1 && g_cmd.calls == 0, "ByID path taken");
    expect(g_byid.type == param_scan_type_data, "type delivered");
    expect(g_byid.path == U(kScanPath), "path delivered");
    expect(g_byid.data == std::string(kScanBytes, sizeof(kScanBytes) - 1), "data delivered");
    expect(g_byid.ctx == U("ctx-info"), "context delivered");
    expect(g_byid.info == U("{\"page\":1}"), "info delivered");
}

void control_byid_empty_data_delivered() {
    dispatch_one(kCallbackName, false);
    expect(g_byid.calls == 1, "ByID path taken");
    expect(g_byid.type == param_scan_type_file && g_byid.data.empty(), "file scan without data delivered");
}

void control_1007_args_delivered() {
    dispatch_one(U("ICA_UNRESOLVED"));
    expect(g_cmd.calls == 1 && g_byid.calls == 0, "EXECUTE METHOD path taken");
    expect(g_cmd.method == U("ICA_UNRESOLVED"), "method name delivered");
    expect(g_cmd.type == param_scan_type_data, "type delivered");
    expect(g_cmd.path == U(kScanPath), "path delivered");
    expect(g_cmd.data == std::string(kScanBytes, sizeof(kScanBytes) - 1), "data delivered");
    expect(g_cmd.ctx == U("ctx-info") && g_cmd.info == U("{\"page\":1}"), "context and info delivered");
}

/* ---- Classes wrappers (built and used by the plugin's commands) ---- */

/* Contracts 1/2: ARRAY_TEXT::toParamAtIndex fills via PA_SetStringInArray
   and must not dispose the transferred strings; reading borrows. */
void control_array_text_transfer() {
    ARRAY_TEXT a;
    a.appendUTF16String(U("a").c_str(), 1);
    a.appendUTF16String(U("bc").c_str(), 2);
    PA_Variable arr = PA_CreateVariable(eVK_ArrayUnicode);
    void *params[1] = { &arr };
    a.toParamAtIndex((PackagePtr)params, 1);
    expect(arr.fType == eVK_ArrayUnicode && arr.uValue.fArray.fNbElements >= 1, "elements returned");
    PA_long32 n = arr.uValue.fArray.fNbElements;
    PA_Unistring *items = (PA_Unistring *)checked(arr.uValue.fArray.fData)->data;
    expect(u16(items[n].fString, items[n].fLength) == U("bc"), "last element delivered");
    size_t owned = g_strings.size();
    ARRAY_TEXT b;
    b.fromParamAtIndex((PackagePtr)params, 1);
    expect(g_strings.size() == owned, "reading borrows the array strings");
    PA_ClearVariable(&arr);
    expect(no_engine_allocations(), "array strings released with the array");
}

/* ---- support/4DPlugin-JSON.cpp (UNREACHABLE: built on macOS, never called) ---- */

void defect_ob_set_s_owner_leak() {
    Obj *o = new_object();
    ob_set_s((PA_ObjectRef)o, "k", "v");
    ob_set_s((PA_ObjectRef)o, L"w", "v");
    expect(o->props.size() == 2, "both properties set");
    release_object(o);
    expect(no_engine_allocations(), "no empty string owner leaked by ob_set_s");
}

void defect_ob_set_a_owner_leak() {
    Obj *o = new_object();
    u16 v = U("v");
    ob_set_a((PA_ObjectRef)o, L"a", L"v");
    ob_set_a((PA_ObjectRef)o, L"b", &v);
    expect(o->props.size() == 2, "both properties set");
    release_object(o);
    expect(no_engine_allocations(), "no empty string owner leaked by ob_set_a");
}

void defect_ob_set_p_owner_leak() {
    Obj *o = new_object();
    ob_set_p((PA_ObjectRef)o, L"p", (PA_Picture)new_picture()); /* consumed by the helper */
    expect(o->props.size() == 1, "picture property set");
    release_object(o);
    expect(no_engine_allocations(), "no empty picture owner leaked by ob_set_p");
}

Obj *sample_object() {
    Obj *o = new_object();
    ob_set_n((PA_ObjectRef)o, L"n", 1.5);
    ob_set_b((PA_ObjectRef)o, L"b", true);
    PA_Variable s; memset(&s, 0, sizeof s);
    s.fType = eVK_Unistring;
    s.uValue.fString = new_string(U("text").c_str(), 4);
    o->props[U("s")] = s;
    return o;
}

void defect_ob_get_a_result_not_cleared() {
    Obj *o = sample_object();
    CUTF8String out;
    expect(ob_get_a((PA_ObjectRef)o, L"s", &out), "property defined");
    expect(out == CUTF8String((const uint8_t *)"text"), "value read");
    release_object(o);
    expect(no_engine_allocations(), "ob_get_a released its copy");
}

void defect_ob_get_b_wrong_kind_not_cleared() {
    Obj *o = sample_object();
    expect(ob_get_b((PA_ObjectRef)o, L"b"), "bool read");
    expect(!ob_get_b((PA_ObjectRef)o, L"s"), "text is not a bool");
    release_object(o);
    expect(no_engine_allocations(), "ob_get_b released its copy");
}

void defect_ob_get_n_wrong_kind_not_cleared() {
    Obj *o = sample_object();
    expect(ob_get_n((PA_ObjectRef)o, L"n") == 1.5, "number read");
    expect(ob_get_n((PA_ObjectRef)o, L"s") == 0.0, "text is not a number");
    release_object(o);
    expect(no_engine_allocations(), "ob_get_n released its copy");
}

void defect_ob_get_c_wrong_kind_not_cleared() {
    Obj *o = sample_object();
    expect(ob_get_c((PA_ObjectRef)o, L"s") == NULL, "text is not a collection");
    release_object(o);
    expect(no_engine_allocations(), "ob_get_c released its copy");
}

void defect_ob_get_o_wrong_kind_not_cleared() {
    Obj *o = sample_object();
    expect(ob_get_o((PA_ObjectRef)o, L"s") == NULL, "text is not an object");
    release_object(o);
    expect(no_engine_allocations(), "ob_get_o released its copy");
}

void guard_ob_get_error_result_untouched() {
    Obj *o = sample_object();
    g_fail_get = true;
    CUTF8String out;
    ob_get_a((PA_ObjectRef)o, L"s", &out);
    ob_get_b((PA_ObjectRef)o, L"s");
    ob_get_n((PA_ObjectRef)o, L"s");
    PA_CollectionRef c = ob_get_c((PA_ObjectRef)o, L"s");
    PA_ObjectRef child = ob_get_o((PA_ObjectRef)o, L"s");
    g_fail_get = false;
    /* Clearing a poisoned result would abort with ENGINE VIOLATION. */
    expect(c == NULL && child == NULL, "failed reference results not returned");
    release_object(o);
    expect(no_engine_allocations(), "nothing leaked after failed gets");
}

void control_ob_get_o_c_transfer() {
    Obj *o = new_object();
    Obj *child = new_object();
    Obj *coll = new_object();
    ob_set_o((PA_ObjectRef)o, L"o", (PA_ObjectRef)child);      /* consumed by the helper */
    ob_set_c((PA_ObjectRef)o, L"c", (PA_CollectionRef)coll);   /* consumed by the helper */
    expect(child->rc == 1 && coll->rc == 1, "values now owned by the parent object");
    PA_ObjectRef got = ob_get_o((PA_ObjectRef)o, L"o");
    PA_CollectionRef gotc = ob_get_c((PA_ObjectRef)o, L"c");
    expect((Obj *)got == child && (Obj *)gotc == coll, "references returned");
    expect(child->rc == 2 && coll->rc == 2, "returned references owned by the caller");
    release_object((Obj *)got);
    release_object((Obj *)gotc);
    release_object(o);
    expect(no_engine_allocations(), "everything released");
}

void control_ob_set_scalars_and_stringify() {
    Obj *o = new_object();
    ob_set_n((PA_ObjectRef)o, L"n", 2.0);
    ob_set_i((PA_ObjectRef)o, L"i", 3);
    ob_set_b((PA_ObjectRef)o, L"b", false);
    ob_set_0((PA_ObjectRef)o, L"z");
    expect(ob_is_defined((PA_ObjectRef)o, L"i") && !ob_is_defined((PA_ObjectRef)o, L"x"), "is defined");
    CUTF8String json;
    ob_stringify((PA_ObjectRef)o, &json);
    expect(json == CUTF8String((const uint8_t *)"{}"), "stringified");
    release_object(o);
    expect(no_engine_allocations(), "scalars and stringify leave nothing behind");
}

const std::map<std::string, std::function<void()>> kTests = {
    { "defect_byid_param_owner_leak", defect_byid_param_owner_leak },
    { "defect_1007_param_owner_leak", defect_1007_param_owner_leak },
    { "defect_byid_result_not_cleared", defect_byid_result_not_cleared },
    { "guard_byid_error_result_untouched", guard_byid_error_result_untouched },
    { "control_byid_args_delivered", control_byid_args_delivered },
    { "control_byid_empty_data_delivered", control_byid_empty_data_delivered },
    { "control_1007_args_delivered", control_1007_args_delivered },
    { "control_array_text_transfer", control_array_text_transfer },
    { "defect_ob_set_s_owner_leak", defect_ob_set_s_owner_leak },
    { "defect_ob_set_a_owner_leak", defect_ob_set_a_owner_leak },
    { "defect_ob_set_p_owner_leak", defect_ob_set_p_owner_leak },
    { "defect_ob_get_a_result_not_cleared", defect_ob_get_a_result_not_cleared },
    { "defect_ob_get_b_wrong_kind_not_cleared", defect_ob_get_b_wrong_kind_not_cleared },
    { "defect_ob_get_n_wrong_kind_not_cleared", defect_ob_get_n_wrong_kind_not_cleared },
    { "defect_ob_get_c_wrong_kind_not_cleared", defect_ob_get_c_wrong_kind_not_cleared },
    { "defect_ob_get_o_wrong_kind_not_cleared", defect_ob_get_o_wrong_kind_not_cleared },
    { "guard_ob_get_error_result_untouched", guard_ob_get_error_result_untouched },
    { "control_ob_get_o_c_transfer", control_ob_get_o_c_transfer },
    { "control_ob_set_scalars_and_stringify", control_ob_set_scalars_and_stringify },
};

} // namespace

int main(int argc, char **argv) {
    gCall4D = (Call4DProcPtr)engine;
    if(argc == 2 && std::string(argv[1]) == "--list") {
        for(auto &t : kTests) printf("%s\n", t.first.c_str());
        return 0;
    }
    if(argc != 2 || !kTests.count(argv[1])) { fprintf(stderr, "usage: %s --list | <test>\n", argv[0]); return 2; }
    kTests.at(argv[1])();
    printf("PASS %s\n", argv[1]);
    return 0;
}
