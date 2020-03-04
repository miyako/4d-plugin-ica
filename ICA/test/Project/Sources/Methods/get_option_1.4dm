//%attributes = {"invisible":true}
ARRAY TEXT:C222($scanners;0)
ICA SCANNERS LIST ($scanners)

If (Size of array:C274($scanners)#0)
	
	$scanner:=$scanners{1}
	
	  //these options can be set/get without opening the scanner
	$folderPath:=ICA Get scan option ($scanner;Scanner folder path)
	$documentName:=ICA Get scan option ($scanner;Scanner document name)
	$iamgeType:=ICA Get scan option ($scanner;Scanner image type)
	$transferMode:=Num:C11(ICA Get scan option ($scanner;Scanner transfer mode))
	$maxDataSize:=Num:C11(ICA Get scan option ($scanner;Scanner max data size))
	
	ICA SET SCAN OPTION ($scanner;Scanner folder path;Temporary folder:C486)
	ICA SET SCAN OPTION ($scanner;Scanner document name;"scan by 4D")
	ICA SET SCAN OPTION ($scanner;Scanner image type;String:C10(Scanner image type PDF))
	ICA SET SCAN OPTION ($scanner;Scanner transfer mode;String:C10(Scanner transfer mode file))
	
	$folderPath:=ICA Get scan option ($scanner;Scanner folder path)
	$documentName:=ICA Get scan option ($scanner;Scanner document name)
	$iamgeType:=ICA Get scan option ($scanner;Scanner image type)
	
End if 