[CmdletBinding()]
param(
	[switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
	throw "Project virtual environment not found. Create it and install requirements-dev.txt first."
}

Push-Location $projectRoot
try {
	$version = & $python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"
	if ($LASTEXITCODE -ne 0) { throw 'Could not read project version from pyproject.toml.' }

	$releaseDir = Join-Path $projectRoot 'release'
	$archive = Join-Path $releaseDir "StudyTracker-$version-Windows-x64.zip"
	if (Test-Path $archive) {
		throw "Release archive already exists; move it before creating another: $archive"
	}

	if ($SkipTests) {
		Write-Warning 'Pytest was explicitly skipped; do not publish without reviewing test status.'
	}
	else {
		& $python -m pytest -q
		if ($LASTEXITCODE -ne 0) { throw "Pytest failed with exit code $LASTEXITCODE." }
	}

	& $python -m ruff check .
	if ($LASTEXITCODE -ne 0) { throw "Ruff failed with exit code $LASTEXITCODE." }

	$bundleDir = Join-Path $projectRoot 'build\release-dist'
	$stdoutLog = Join-Path $env:TEMP 'study-tracker-pyinstaller.stdout.log'
	$stderrLog = Join-Path $env:TEMP 'study-tracker-pyinstaller.stderr.log'
	$arguments = "-m PyInstaller --noconfirm --clean --distpath `"$bundleDir`" packaging\study_tracker.spec"
	$process = Start-Process `
		-FilePath $python `
		-ArgumentList $arguments `
		-WorkingDirectory $projectRoot `
		-RedirectStandardOutput $stdoutLog `
		-RedirectStandardError $stderrLog `
		-NoNewWindow `
		-Wait `
		-PassThru
	if ($process.ExitCode -ne 0) {
		Get-Content $stdoutLog -Tail 40 -ErrorAction SilentlyContinue
		Get-Content $stderrLog -Tail 40 -ErrorAction SilentlyContinue
		throw "PyInstaller failed with exit code $($process.ExitCode)."
	}
	Remove-Item $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue

	$bundle = Join-Path $bundleDir 'StudyTracker'
	$executable = Join-Path $bundle 'StudyTracker.exe'
	if (-not (Test-Path $executable)) {
		throw "Expected executable was not produced: $executable"
	}

	New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
	$temporaryArchive = "$archive.tmp.zip"
	$releaseFiles = @(
		$bundle,
		(Join-Path $projectRoot 'README.md'),
		(Join-Path $projectRoot 'LICENSE'),
		(Join-Path $projectRoot 'CONTRIBUTING.md'),
		(Join-Path $projectRoot 'SECURITY.md'),
		(Join-Path $projectRoot 'docs\csv-format.md'),
		(Join-Path $projectRoot 'docs\RELIABILITY.md')
	)
	Compress-Archive -Path $releaseFiles -DestinationPath $temporaryArchive -CompressionLevel Optimal
	Move-Item -LiteralPath $temporaryArchive -Destination $archive

	$hash = (Get-FileHash -Path $archive -Algorithm SHA256).Hash.ToLowerInvariant()
	"$hash  $(Split-Path $archive -Leaf)" |
		Set-Content -Path "$archive.sha256" -Encoding ascii

	Write-Host "Built $executable"
	Write-Host "Release archive: $archive"
	Write-Host "SHA-256: $archive.sha256"
}
finally {
	Pop-Location
}
