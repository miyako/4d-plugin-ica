//%attributes = {"invisible":true}
ARRAY TEXT:C222($scanners;0)
ICA SCANNERS LIST ($scanners)

If (Size of array:C274($scanners)#0)
	
	$scanner:=$scanners{1}
	
	ICA OPEN SCANNER SESSION ($scanner;Scanner source document feeder)
	
	ARRAY TEXT:C222($scanners;0)
	ICA SCANNERS LIST ($scanners)
	
	$json:=$scanners{0}
	ARRAY OBJECT:C1221($scannersInfo;0)
	JSON PARSE ARRAY:C1219($json;$scannersInfo)
	
	  //options available after opening the scanner:
	
	  //supportedBitDepths[] (r/o)
	  //supportedMeasurementUnits[] (r/o)
	  //preferredScaleFactors[] (r/o)
	  //supportedScaleFactors[] (r/o)
	  //preferredResolutions[] (r/o)
	  //supportedResolutions[] (r/o)
	  //scanProgressPercentDone (r/o)
	  //measurementUnit (r/o)
	  //nativeXResolution (r/o)
	  //nativeYResolution (r/o)
	  //overviewResolution (r/o)
	  //thresholdForBlackAndWhiteScanning (r/o)
	  //defaultThresholdForBlackAndWhiteScanning (r/o)
	  //overviewScanInProgress (r/o)
	  //canPerformOverviewScan (r/o)
	  //scanInProgress (r/o)
	  //acceptsThresholdForBlackAndWhiteScanning (r/o)
	  //usesThresholdForBlackAndWhiteScanning (r/o)
	
	  //~all document types~
	
	  //supportedDocumentTypes[] (r/o)
	  //documentSize (r/o)
	  //documentType (Scanner document type:6)
	
	  //~document feeder only~
	
	  //documentLoaded (r/o)
	  //reverseFeederPageOrder (r/o)
	  //supportsDuplexScanning (r/o)
	  //documentSize (r/o)
	
	  //oddPageOrientation (Scanner odd page orientation:3)
	  //evenPageOrientation (Scanner even page orientation:4)
	  //duplexScanningEnabled (Scanner duplex enabled:5)
	  //scaleFactor (Scanner scale factor:7)
	  //resolution (Scanner resolution:8)
	  //bitDepth (Scanner bit depth:9)
	  //pixelDataType (Scanner pixel data type:10)
	
	ICA CLOSE SCANNER SESSION ($scanner)
	
End if 