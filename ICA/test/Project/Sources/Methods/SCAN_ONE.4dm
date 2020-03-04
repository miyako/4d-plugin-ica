//%attributes = {"invisible":true}
C_LONGINT:C283($1;$type)
C_TEXT:C284($2;$path)
C_BLOB:C604($3;$data)
C_TEXT:C284($4;$userInfo)
C_TEXT:C284($5;$dataInfo)

$type:=$1
$path:=$2
$data:=$3
$userInfo:=$4
$dataInfo:=$5

<>SCAN_ERROR:=""

Case of 
	: ($type=0)  //path
		
		If (Test path name:C476($path)=Is a document:K24:1)
			C_PICTURE:C286($image)
			READ PICTURE FILE:C678($path;$image)
			<>SCAN_IMAGE:=<>SCAN_IMAGE+$image
		End if 
		
	: ($type=1)  //blob (raw data)
		
		C_OBJECT:C1216($info)
		$info:=JSON Parse:C1218($dataInfo)
		
		$dataSize:=OB Get:C1224($info;"dataSize";Is longint:K8:6)
		$dataNumRows:=OB Get:C1224($info;"dataNumRows";Is longint:K8:6)
		$dataStartRow:=OB Get:C1224($info;"dataStartRow";Is longint:K8:6)
		$bytesPerRow:=OB Get:C1224($info;"bytesPerRow";Is longint:K8:6)
		$numComponents:=OB Get:C1224($info;"numComponents";Is longint:K8:6)
		$bitsPerComponent:=OB Get:C1224($info;"bitsPerComponent";Is longint:K8:6)
		$bitsPerPixel:=OB Get:C1224($info;"bitsPerPixel";Is longint:K8:6)
		$fullImageHeight:=OB Get:C1224($info;"fullImageHeight";Is longint:K8:6)
		$fullImageWidth:=OB Get:C1224($info;"fullImageWidth";Is longint:K8:6)
		$isBigEndian:=OB Get:C1224($info;"isBigEndian";Is boolean:K8:9)
		$pixelDataType:=OB Get:C1224($info;"pixelDataType";Is text:K8:3)
		$colorSyncProfilePath:=OB Get:C1224($info;"colorSyncProfilePath";Is text:K8:3)
		
		COPY BLOB:C558($data;<>SCANNER_DATA;0;BLOB size:C605(<>SCANNER_DATA);BLOB size:C605($data))
		
	: ($type=2)  //success
		<>SCANNER_INFO:="DONE!"
	: ($type=3)  //error
		<>SCANNER_INFO:="ERROR!"
		<>SCAN_ERROR:=$dataInfo
	Else 
		
End case 

POST OUTSIDE CALL:C329(-1)