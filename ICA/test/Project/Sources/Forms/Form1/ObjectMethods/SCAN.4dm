<>SCANNER_INFO:=""

If (<>SCANNER_ID#"")
	
	C_OBJECT:C1216($userInfo)
	OB SET:C1220($userInfo;\
		"currentFormName";Current form name:C1298;\
		"currentFormWindow";Current form window:C827;\
		"currentProcessName";Current process name:C1392;\
		"currentProcess";Current process:C322)
	
	$p:=New process:C317("SCAN";0;Generate UUID:C1066;<>SCANNER_ID;$userInfo)
	
End if 