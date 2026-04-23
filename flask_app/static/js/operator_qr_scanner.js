(() => {
    const form = document.getElementById('qrScannerForm');
    const qrInput = document.getElementById('qr_data');
    const scanSourceInput = document.getElementById('scan_source');
    const startButton = document.getElementById('startCamera');
    const stopButton = document.getElementById('stopCamera');
    const qrImageFileInput = document.getElementById('qrImageFile');
    const qrImagePreview = document.getElementById('qrImagePreview');
    const cameraContainer = document.getElementById('cameraContainer');
    const qrReader = document.getElementById('qr-reader');
    const scannerStatus = document.getElementById('scannerStatus');

    if (!form || !qrInput || !scanSourceInput || !startButton || !stopButton || !qrImageFileInput || !qrImagePreview || !cameraContainer || !qrReader || !scannerStatus) {
        return;
    }

    let scanner = null;
    let scannerRunning = false;
    let submitLocked = false;
    let fallbackDetector = null;
    let fallbackVideo = null;
    let fallbackStream = null;
    let fallbackFrameHandle = null;
    let usingFallbackScanner = false;
    let audioContext = null;

    function setStatus(message, className) {
        scannerStatus.className = `small mt-3 mb-0 ${className}`;
        scannerStatus.textContent = message;
    }

    function playTone(frequency, durationMs) {
        try {
            const AudioContextClass = window.AudioContext || window.webkitAudioContext;
            if (!AudioContextClass) {
                return;
            }

            if (!audioContext) {
                audioContext = new AudioContextClass();
            }

            const oscillator = audioContext.createOscillator();
            const gain = audioContext.createGain();
            oscillator.type = 'sine';
            oscillator.frequency.value = frequency;
            gain.gain.value = 0.05;
            oscillator.connect(gain);
            gain.connect(audioContext.destination);
            oscillator.start();
            oscillator.stop(audioContext.currentTime + (durationMs / 1000));
        } catch (error) {
            // Audio feedback is optional.
        }
    }

    function isSecureOriginForCamera() {
        const localhostHosts = new Set(['localhost', '127.0.0.1', '::1']);
        return window.isSecureContext || localhostHosts.has(window.location.hostname);
    }

    function scannerLibraryReady() {
        return typeof window.Html5Qrcode !== 'undefined';
    }

    function barcodeDetectorReady() {
        return typeof window.BarcodeDetector !== 'undefined';
    }

    function resetScannerUi() {
        cameraContainer.style.display = 'none';
        startButton.style.display = 'inline-block';
        stopButton.style.display = 'none';
        startButton.disabled = false;
        stopButton.disabled = true;
        scannerRunning = false;
    }

    async function clearHtml5Scanner() {
        if (!scanner) {
            return;
        }

        try {
            await scanner.clear();
        } catch (error) {
            // Ignore cleanup errors when the scanner has no rendered state.
        }
    }

    function ensureFallbackVideo() {
        if (!fallbackVideo) {
            fallbackVideo = document.createElement('video');
            fallbackVideo.setAttribute('autoplay', '');
            fallbackVideo.setAttribute('muted', '');
            fallbackVideo.setAttribute('playsinline', '');
            fallbackVideo.style.width = '100%';
            fallbackVideo.style.minHeight = '320px';
            fallbackVideo.style.objectFit = 'cover';
            fallbackVideo.style.background = '#000';
        }

        qrReader.innerHTML = '';
        qrReader.appendChild(fallbackVideo);
    }

    async function clearFallbackScanner() {
        if (fallbackFrameHandle) {
            window.cancelAnimationFrame(fallbackFrameHandle);
            fallbackFrameHandle = null;
        }

        if (fallbackStream) {
            fallbackStream.getTracks().forEach((track) => track.stop());
            fallbackStream = null;
        }

        if (fallbackVideo) {
            fallbackVideo.pause();
            fallbackVideo.srcObject = null;
        }

        usingFallbackScanner = false;
        qrReader.innerHTML = '';
    }

    async function clearScanner() {
        await clearHtml5Scanner();
        await clearFallbackScanner();
    }

    async function stopScanner(options = {}) {
        if (scanner && scannerRunning) {
            try {
                await scanner.stop();
            } catch (error) {
                // Ignore stop errors so the user can retry without reloading.
            }
        }

        await clearScanner();
        resetScannerUi();

        if (!options.preserveStatus) {
            setStatus('Camera stopped. You can restart scanning or paste the QR value manually.', 'text-muted');
        }
    }

    function submitDetectedQr(rawValue) {
        const normalizedValue = String(rawValue || '').trim();
        if (!normalizedValue || submitLocked) {
            return;
        }

        submitLocked = true;
        qrInput.value = normalizedValue;
        playTone(880, 180);
        setStatus('QR code detected. Verifying booking now...', 'text-success');

        stopScanner({ preserveStatus: true })
            .finally(() => {
                if (form.requestSubmit) {
                    form.requestSubmit();
                } else {
                    form.submit();
                }
            });
    }

    async function decodeQrImage(file) {
        if (!file) {
            return;
        }

        scanSourceInput.value = 'file';
        submitLocked = false;
        setStatus('Reading QR image...', 'text-muted');
        qrImagePreview.src = URL.createObjectURL(file);
        qrImagePreview.style.display = 'block';

        try {
            let decodedText = '';

            if (scannerLibraryReady()) {
                if (!scanner) {
                    scanner = new window.Html5Qrcode('qr-reader');
                }
                decodedText = await scanner.scanFile(file, true);
            } else if (barcodeDetectorReady() && typeof window.createImageBitmap === 'function') {
                if (!fallbackDetector) {
                    fallbackDetector = new window.BarcodeDetector({ formats: ['qr_code'] });
                }

                const bitmap = await window.createImageBitmap(file);
                try {
                    const detectedCodes = await fallbackDetector.detect(bitmap);
                    decodedText = detectedCodes.length > 0 ? detectedCodes[0].rawValue : '';
                } finally {
                    if (typeof bitmap.close === 'function') {
                        bitmap.close();
                    }
                }
            } else {
                setStatus('Image QR decoding is not available in this browser. Paste the link or token manually.', 'text-danger');
                return;
            }

            submitDetectedQr(decodedText);
        } catch (error) {
            playTone(220, 250);
            setStatus('No readable QR code was found in that image. Try a clearer screenshot or photo.', 'text-danger');
        } finally {
            qrImageFileInput.value = '';
        }
    }

    function normalizeScannerError(error) {
        const errorText = String((error && error.message) || error || '').toLowerCase();

        if (!isSecureOriginForCamera()) {
            return 'Camera scanning is blocked on this page because the app is not running on localhost or HTTPS.';
        }
        if (errorText.includes('permission') || errorText.includes('denied') || errorText.includes('notallowed')) {
            return 'Camera permission was denied. Allow camera access in the browser and try again.';
        }
        if (errorText.includes('notfound') || errorText.includes('no camera') || errorText.includes('devicesnotfound')) {
            return 'No camera was found on this device.';
        }
        if (errorText.includes('notreadable') || errorText.includes('trackstart')) {
            return 'The camera is already being used by another app or browser tab.';
        }
        if (errorText.includes('secure') || errorText.includes('https')) {
            return 'Camera scanning needs localhost or HTTPS in this browser.';
        }

        return 'Camera could not be started. Try Chrome or Edge, allow camera permission, and use localhost or HTTPS.';
    }

    function scanFallbackFrame() {
        if (!usingFallbackScanner || !fallbackDetector || !fallbackVideo) {
            return;
        }

        fallbackDetector.detect(fallbackVideo)
            .then((detectedCodes) => {
                if (detectedCodes && detectedCodes.length > 0) {
                    submitDetectedQr(detectedCodes[0].rawValue);
                    return;
                }

                fallbackFrameHandle = window.requestAnimationFrame(scanFallbackFrame);
            })
            .catch(() => {
                fallbackFrameHandle = window.requestAnimationFrame(scanFallbackFrame);
            });
    }

    async function startWithBestCamera(html5QrCode, config) {
        try {
            await html5QrCode.start(
                { facingMode: 'environment' },
                config,
                submitDetectedQr,
                () => {}
            );
            return true;
        } catch (facingModeError) {
            const cameras = await window.Html5Qrcode.getCameras();
            if (!cameras || !cameras.length) {
                throw facingModeError;
            }

            const preferredCamera = cameras.find((camera) =>
                /back|rear|environment/i.test(String(camera.label || ''))
            ) || cameras[0];

            await html5QrCode.start(
                { deviceId: { exact: preferredCamera.id } },
                config,
                submitDetectedQr,
                () => {}
            );
            return true;
        }
    }

    async function startFallbackCameraScanner() {
        if (!barcodeDetectorReady()) {
            throw new Error('No compatible QR scanner is available in this browser.');
        }

        if (!fallbackDetector) {
            fallbackDetector = new window.BarcodeDetector({ formats: ['qr_code'] });
        }

        ensureFallbackVideo();
        fallbackStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: { ideal: 'environment' } },
            audio: false,
        });

        fallbackVideo.srcObject = fallbackStream;
        await fallbackVideo.play();

        usingFallbackScanner = true;
        scanFallbackFrame();
    }

    async function startScanner() {
        if (scannerRunning) {
            return;
        }

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            setStatus('Camera access is not available on this device or browser.', 'text-danger');
            return;
        }

        if (!isSecureOriginForCamera()) {
            setStatus('Camera scanning needs localhost or HTTPS. Open the app with localhost or a secure URL, then try again.', 'text-danger');
            return;
        }

        if (!scannerLibraryReady() && !barcodeDetectorReady()) {
            setStatus('No supported QR scanner is available in this browser. Paste the link or token manually instead.', 'text-danger');
            return;
        }

        submitLocked = false;
        scanSourceInput.value = 'camera';
        startButton.disabled = true;
        cameraContainer.style.display = 'block';
        startButton.style.display = 'none';
        stopButton.style.display = 'inline-block';
        stopButton.disabled = true;
        setStatus('Opening camera...', 'text-muted');

        const config = {
            fps: 10,
            qrbox: { width: 250, height: 250 },
            aspectRatio: 1,
        };

        try {
            if (scannerLibraryReady()) {
                if (!scanner) {
                    scanner = new window.Html5Qrcode('qr-reader');
                }
                await startWithBestCamera(scanner, config);
            } else {
                await startFallbackCameraScanner();
            }

            scannerRunning = true;
            stopButton.disabled = false;
            setStatus('Point the camera at the ticket QR code. Detection will submit automatically.', 'text-muted');
        } catch (error) {
            await stopScanner({ preserveStatus: true });
            playTone(220, 250);
            setStatus(normalizeScannerError(error), 'text-danger');
        } finally {
            startButton.disabled = false;
        }
    }

    startButton.addEventListener('click', startScanner);
    stopButton.addEventListener('click', () => stopScanner());
    qrInput.addEventListener('input', () => {
        if (!qrInput.value.trim()) {
            scanSourceInput.value = 'manual';
        }
    });
    qrImageFileInput.addEventListener('change', (event) => {
        const [file] = event.target.files || [];
        decodeQrImage(file);
    });
    window.addEventListener('beforeunload', () => {
        stopScanner({ preserveStatus: true });
    });
})();
