$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$compilerRoot = Join-Path $projectRoot '.build-tools/msys/clang64/bin'
$compiler = Join-Path $compilerRoot 'clang++.exe'
$archiver = Join-Path $compilerRoot 'llvm-ar.exe'
$previousStage = Join-Path $projectRoot '.build-tools/native'
$stage = Join-Path $projectRoot '.build-tools/frontend-workspace-20261002'
New-Item -ItemType Directory -Path $stage -Force | Out-Null
$includes = @('kar','melder','sys','dwsys','stat','fon','dwtools','LPC','external/portaudio','external/flac','external/mp3','external/espeak') | ForEach-Object { '-I'+(Join-Path $projectRoot $_) }
$object = Join-Path $stage 'praat_python.o'
& $compiler -c -std=gnu++17 -municode -D_FILE_OFFSET_BITS=64 -march=x86-64-v3 -O3 -Wshadow @includes (Join-Path $projectRoot 'sys/praat_python.cpp') -o $object
if ($LASTEXITCODE -ne 0) { throw 'Python runner compilation failed' }
$archive = Join-Path $stage 'libsys.a'
Copy-Item -LiteralPath (Join-Path $previousStage 'libsys.a') -Destination $archive
& $archiver r $archive $object
if ($LASTEXITCODE -ne 0) { throw 'System archive update failed' }
$libraries = @('fon/libfon.a','artsynth/libartsynth.a','FFNet/libFFNet.a','gram/libgram.a','EEG/libEEG.a','LPC/libLPC.a','dwtools/libdwtools.a','sensors/libsensors.a') | ForEach-Object { Join-Path $projectRoot $_ }
$libraries += Join-Path $previousStage 'libfoned.a'
$libraries += @('fon/libfon.a','stat/libstat.a','dwsys/libdwsys.a') | ForEach-Object { Join-Path $projectRoot $_ }
$libraries += $archive
$libraries += @('melder/libmelder.a','kar/libkar.a','external/espeak/libespeak.a','external/portaudio/libportaudio.a','external/flac/libflac.a','external/lame/liblame.a','external/mp3/libmp3.a','external/glpk/libglpk.a','external/clapack/libclapack.a','external/gsl/libgsl.a','external/num/libnum.a','external/vorbis/libvorbis.a','external/opusfile/libopusfile.a','external/whispercpp/libwhisper.a','external/blake3/libblake3.a','external/zlib/libzlib.a') | ForEach-Object { Join-Path $projectRoot $_ }
$native = Join-Path $stage 'Praat.exe'
& $compiler -o $native (Join-Path $projectRoot 'main/main_Praat.o') (Join-Path $projectRoot 'main/praat_win.o') @libraries -lwinmm -lwsock32 -lcomctl32 -lole32 -lgdi32 -lgdiplus -lcomdlg32 -lwinspool -lshell32 -luxtheme -ldwmapi -ladvapi32 -luuid -static -lc++ -lc++abi -mwindows
if ($LASTEXITCODE -ne 0) { throw 'Praat link failed' }
$sourceHashes = [ordered]@{}
foreach ($relative in @('sys/praat_python.cpp','sys/praat_python_workspace.h','Makefile')) {
    $sourceHashes[$relative] = (Get-FileHash -LiteralPath (Join-Path $projectRoot $relative) -Algorithm SHA256).Hash.ToLowerInvariant()
}
$report = [ordered]@{
    native_sha256 = (Get-FileHash -LiteralPath $native -Algorithm SHA256).Hash.ToLowerInvariant()
    previous_native_sha256 = (Get-FileHash -LiteralPath (Join-Path $previousStage 'Praat.exe') -Algorithm SHA256).Hash.ToLowerInvariant()
    candidate = $native
    sources = $sourceHashes
    compiler = $compiler
    built_at = [DateTime]::UtcNow.ToString('o')
}
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'python-workspace-native-build.json'), ($report | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
Get-FileHash -LiteralPath $native -Algorithm SHA256 | Format-List Path,Hash
