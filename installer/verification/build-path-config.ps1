$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$compilerRoot = Join-Path $projectRoot '.build-tools/msys/clang64/bin'
$compiler = Join-Path $compilerRoot 'clang++.exe'
$archiver = Join-Path $compilerRoot 'llvm-ar.exe'
$stage = Join-Path $projectRoot '.build-tools/native'
New-Item -ItemType Directory -Path $stage -Force | Out-Null
$units = @('sys/PraatAiControl.cpp','sys/praat.cpp','sys/praat_translate.cpp','foned/FunctionEditor.cpp')
$includes = @('kar','melder','sys','dwsys','stat','fon','dwtools','LPC','external/portaudio','external/flac','external/mp3','external/espeak') | ForEach-Object { '-I'+(Join-Path $projectRoot $_) }
foreach ($unit in $units) {
    $object = Join-Path $stage ([IO.Path]::GetFileNameWithoutExtension($unit)+'.o')
    & $compiler -c -std=gnu++17 -municode -D_FILE_OFFSET_BITS=64 -march=x86-64-v3 -O3 -Wshadow @includes (Join-Path $projectRoot $unit) -o $object
    if ($LASTEXITCODE -ne 0) { throw "Compilation failed: $unit" }
    Write-Output "Compiled $unit"
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'sys/libsys.a') -Destination (Join-Path $stage 'libsys.a')
& $archiver r (Join-Path $stage 'libsys.a') (Join-Path $stage 'PraatAiControl.o') (Join-Path $stage 'praat.o') (Join-Path $stage 'praat_translate.o')
if ($LASTEXITCODE -ne 0) { throw 'System archive update failed' }
Copy-Item -LiteralPath (Join-Path $projectRoot 'foned/libfoned.a') -Destination (Join-Path $stage 'libfoned.a')
& $archiver r (Join-Path $stage 'libfoned.a') (Join-Path $stage 'FunctionEditor.o')
if ($LASTEXITCODE -ne 0) { throw 'Editor archive update failed' }
$libraries = @('fon/libfon.a','artsynth/libartsynth.a','FFNet/libFFNet.a','gram/libgram.a','EEG/libEEG.a','LPC/libLPC.a','dwtools/libdwtools.a','sensors/libsensors.a') | ForEach-Object { Join-Path $projectRoot $_ }
$libraries += Join-Path $stage 'libfoned.a'
$libraries += @('fon/libfon.a','stat/libstat.a','dwsys/libdwsys.a') | ForEach-Object { Join-Path $projectRoot $_ }
$libraries += Join-Path $stage 'libsys.a'
$libraries += @('melder/libmelder.a','kar/libkar.a','external/espeak/libespeak.a','external/portaudio/libportaudio.a','external/flac/libflac.a','external/lame/liblame.a','external/mp3/libmp3.a','external/glpk/libglpk.a','external/clapack/libclapack.a','external/gsl/libgsl.a','external/num/libnum.a','external/vorbis/libvorbis.a','external/opusfile/libopusfile.a','external/whispercpp/libwhisper.a','external/blake3/libblake3.a','external/zlib/libzlib.a') | ForEach-Object { Join-Path $projectRoot $_ }
$native = Join-Path $stage 'Praat.exe'
& $compiler -o $native (Join-Path $projectRoot 'main/main_Praat.o') (Join-Path $projectRoot 'main/praat_win.o') @libraries -lwinmm -lwsock32 -lcomctl32 -lole32 -lgdi32 -lgdiplus -lcomdlg32 -lwinspool -lshell32 -luxtheme -ldwmapi -static -lc++ -lc++abi -mwindows
if ($LASTEXITCODE -ne 0) { throw 'Praat link failed' }
Write-Output "Built $native"
