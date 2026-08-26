Set WshShell = CreateObject("WScript.Shell")
strDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = strDir
WshShell.Run Chr(34) & strDir & "\.venv\Scripts\pythonw.exe" & Chr(34) & " " & Chr(34) & strDir & "\app.py" & Chr(34), 0, False
Set WshShell = Nothing
