//%attributes = {"invisible":true}
ARRAY TEXT:C222($scanners;0)
ICA SCANNERS LIST ($scanners)

If (Size of array:C274($scanners)#0)
	
	$scanner:=$scanners{1}
	
	  //these options require the scanner to be open
	
	ICA OPEN SCANNER SESSION ($scanner;Scanner source document feeder)
	
	$evenPageOrientation:=Num:C11(ICA Get scan option ($scanner;Scanner even page orientation))
	$oddPageOrientation:=Num:C11(ICA Get scan option ($scanner;Scanner odd page orientation))
	$duplexEnabled:=Num:C11(ICA Get scan option ($scanner;Scanner duplex enabled))
	$scaleFactor:=Num:C11(ICA Get scan option ($scanner;Scanner scale factor))
	$resolution:=Num:C11(ICA Get scan option ($scanner;Scanner resolution))
	$bitDepth:=Num:C11(ICA Get scan option ($scanner;Scanner bit depth))
	$pixelDataType:=Num:C11(ICA Get scan option ($scanner;Scanner pixel data type))
	
	ICA CLOSE SCANNER SESSION ($scanner)
	
End if 