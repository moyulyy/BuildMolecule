Option Explicit
' Launch MK-MOLE without any console window (double-click this file).
Dim fso, shell, baseDir, exePath, scriptPath
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = baseDir

exePath = baseDir & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(exePath) Then exePath = "pythonw.exe"

scriptPath = baseDir & "\main.pyw"
shell.Run """" & exePath & """ """ & scriptPath & """", 0, False
