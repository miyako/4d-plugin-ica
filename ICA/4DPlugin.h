/* --------------------------------------------------------------------------------
 #
 #	4DPlugin.h
 #	source generated by 4D Plugin Wizard
 #	Project : ImageCaptureCore
 #	author : miyako
 #	2017/09/07
 #
 # --------------------------------------------------------------------------------*/

#include "libjson_methods.h"

typedef PA_long32 process_number_t;
typedef PA_long32 process_stack_size_t;
typedef PA_long32 method_id_t;
typedef PA_Unichar* process_name_t;

typedef enum
{
	param_data_type_text = 0,
	param_data_type_blob = 1
}param_data_type_t;

typedef enum
{
	param_scan_type_file = 0,
	param_scan_type_data = 1,
	param_scan_type_success = 2,
	param_scan_type_error = 3
}param_scan_type_t;

typedef CUTF16String param_scan_context_info_t;
typedef CUTF16String param_scan_info_t;
typedef CUTF16String param_scan_path_t;
typedef std::vector<uint8_t> param_scan_data_t;

#if VERSIONMAC
#import <objc/runtime.h>
#import <ImageCaptureCore/ImageCaptureCore.h>
#define ICDeviceAnyScanner ICDeviceTypeMaskScanner\
| ICDeviceLocationTypeMaskLocal\
| ICDeviceLocationTypeMaskShared\
| ICDeviceLocationTypeMaskBonjour\
| ICDeviceLocationTypeMaskBluetooth\
| ICDeviceLocationTypeMaskRemote

@interface Scanner : NSObject<ICScannerDeviceDelegate>
{
	ICScannerDevice *_scanner;
	BOOL _waiting;
	NSInteger _error;
}

- (id)initWithScanner:(ICScannerDevice *)scanner;
- (void)setScanner:(ICScannerDevice *)scanner;
- (BOOL)openForSource:(ICScannerFunctionalUnitType)source timeout:(NSUInteger)seconds;
- (BOOL)closeWithTimeout:(NSUInteger)seconds;
- (void)requestScan;
- (void)cancelScan;

@end

@interface ScannerBrowser : NSObject
<ICDeviceBrowserDelegate>
{
	NSMutableArray *_scanners;
}

- (ICScannerDevice *)scannerForIdentifier:(NSString *)uuid;

@property(retain, readonly) NSMutableArray *scanners;

@end

#endif

// --- ImageCaptureCore (macOS)
void ICA_SCANNERS_LIST(sLONG_PTR *pResult, PackagePtr pParams);
void ICA_SET_SCAN_OPTION(sLONG_PTR *pResult, PackagePtr pParams);
void ICA_OPEN_SCANNER_SESSION(sLONG_PTR *pResult, PackagePtr pParams);
void ICA_CLOSE_SCANNER_SESSION(sLONG_PTR *pResult, PackagePtr pParams);
void ICA_SCAN(sLONG_PTR *pResult, PackagePtr pParams);
void ICA_CANCEL(sLONG_PTR *pResult, PackagePtr pParams);
void ICA_Get_scan_option(sLONG_PTR *pResult, PackagePtr pParams);