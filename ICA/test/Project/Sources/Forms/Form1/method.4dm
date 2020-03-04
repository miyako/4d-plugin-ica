$event:=Form event:C388

Case of 
	: ($event=On Load:K2:1)
		
		C_PICTURE:C286(<>SCAN_IMAGE;<>SCANNER_ICON)
		<>SCAN_IMAGE:=<>SCAN_IMAGE*0
		<>SCANNER_ICON:=<>SCANNER_ICON*0
		
		C_TEXT:C284(<>SCANNER_ID;<>SCANNER_INFO)
		<>SCANNER_ID:=""
		<>SCANNER_INFO:=""
		<>SCAN_ERROR:=""
		
		C_BLOB:C604(<>SCANNER_DATA)
		
		ARRAY TEXT:C222($scanners;0)
		ICA SCANNERS LIST ($scanners)
		
		If (Size of array:C274($scanners)#0)
			
			<>SCANNER_ID:=$scanners{1}
			
			$json:=$scanners{0}
			ARRAY OBJECT:C1221($scannersInfo;0)
			JSON PARSE ARRAY:C1219($json;$scannersInfo)
			
			C_OBJECT:C1216($scannerInfo)
			$scannerInfo:=$scannersInfo{1}
			$iconPath:=OB Get:C1224($scannerInfo;"iconPath";Is text:K8:3)
			
			If (Is picture file:C1113($iconPath))
				READ PICTURE FILE:C678($iconPath;<>SCANNER_ICON)
			End if 
			
		Else 
			OBJECT SET RGB COLORS:C628(<>SCAN_IMAGE;0x00333333;Background color none:K23:10)
		End if 
		
	: ($event=On Unload:K2:2)
		
End case 