//%attributes = {"invisible":true}
ARRAY TEXT:C222($scanners; 0)
ICA SCANNERS LIST($scanners)

$json:=$scanners{0}
ARRAY OBJECT:C1221($scannersInfo; 0)
JSON PARSE ARRAY:C1219($json; $scannersInfo)

//options available before opening the scanner:

//name (r/o)
//modulePath (r/o)
//moduleVersion (r/o)
//autolaunchApplicationPath (r/o)
//persistentIDString (r/o)
//UUIDString (r/o)
//locationDescription (r/o)
//serialNumberString (r/o)
//transportType (r/o)
//ICTransportTypeTCPIP (r/o)
//ipAddress (r/o)
//iconPath (r/o)
//isRemote (r/o)
//isShared (r/o)
//hasConfigurableWiFiInterface (r/o)
//hasOpenSession (r/o)
//usbVendorID (r/o)
//usbProductID (r/o)
//usbLocationID (r/o)
//moduleExecutableArchitecture (r/o)

//downloadsDirectory (Scanner folder path:0)
//documentName (Scanner document name:1)
//documentUTI (Scanner image type:2)
//maxMemoryBandSize (Scanner max data size:11)
//transferMode (Scanner transfer mode:12)