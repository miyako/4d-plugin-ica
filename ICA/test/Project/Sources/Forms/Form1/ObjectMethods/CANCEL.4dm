<>SCANNER_INFO:=""

If (<>SCANNER_ID#"")
	
	$p:=New process:C317("SCAN_CANCEL";0;Generate UUID:C1066;<>SCANNER_ID)
	
End if 