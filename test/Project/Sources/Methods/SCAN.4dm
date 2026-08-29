//%attributes = {"invisible":true}
C_TEXT:C284($1; $scanner)
C_OBJECT:C1216($2; $userInfo)

$scanner:=$1
$userInfo:=$2

If (False:C215)  //use BLOB; not recommended
	ICA SET SCAN OPTION($scanner; Scanner image type; String:C10(Scanner image type JPEG))
	ICA SET SCAN OPTION($scanner; Scanner transfer mode; String:C10(Scanner transfer mode data))
	SET BLOB SIZE:C606(<>SCANNER_DATA; 0)
Else 
	ICA SET SCAN OPTION($scanner; Scanner image type; String:C10(Scanner image type PDF))
	ICA SET SCAN OPTION($scanner; Scanner transfer mode; String:C10(Scanner transfer mode file))
End if 

ICA OPEN SCANNER SESSION($scanner; Scanner source document feeder)

ICA SCAN($scanner; "SCAN_ONE"; JSON Stringify:C1217($userInfo))