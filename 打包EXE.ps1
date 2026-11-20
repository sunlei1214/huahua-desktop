# 华华 & 熙熙 packaging script
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    python -m pip install pyinstaller
}

if (-not (Test-Path 'runtime\mothx.exe')) {
    Write-Warning '未找到 runtime\mothx.exe：构建出的 EXE 将没有 Agent 运行时。'
}
$runtimeData = @()
if (Test-Path 'runtime\mothx.exe') {
    $runtimeData = @('--add-data', 'runtime;runtime')
}

$buildArgs = @(
    '--noconfirm', '--clean', '--onefile', '--windowed', '--noupx',
    '--name', '华华',
    '--icon', 'assets\icon.ico',
    '--add-data', 'assets;assets'
) + $runtimeData + @(
    '--collect-submodules', 'markdown',
    '--hidden-import', 'fitz',
    '--hidden-import', 'pypdf',
    '--hidden-import', 'docx',
    '--hidden-import', 'pptx',
    '--hidden-import', 'openpyxl',
    '--hidden-import', 'cv2',
    '--hidden-import', 'PIL',
    '--hidden-import', 'PySide6.QtMultimedia',
    '--exclude-module', 'pandas',
    '--exclude-module', 'scipy',
    '--exclude-module', 'matplotlib',
    '--exclude-module', 'pyarrow',
    '--exclude-module', 'tkinter',
    '--exclude-module', 'win32com',
    '--exclude-module', 'pythoncom',
    '--exclude-module', 'pywintypes',
    'main.py'
)

python -m PyInstaller @buildArgs
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

Copy-Item 'dist\华华.exe' '.\华华.exe' -Force
$sizeMB = [math]::Round((Get-Item '.\华华.exe').Length / 1MB, 1)
Write-Host ''
Write-Host "打包完成：华华.exe（$sizeMB MB）"
