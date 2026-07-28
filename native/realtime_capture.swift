import AppKit
import AVFoundation
import CoreAudio
import Darwin
import Foundation

@MainActor
final class ProductApplicationDelegate: NSObject, NSApplicationDelegate {
    private struct RuntimeMarker: Codable {
        let buildID: String
        let instanceID: String
        let pid: Int32

        enum CodingKeys: String, CodingKey {
            case buildID = "build_id"
            case instanceID = "instance_id"
            case pid
        }
    }

    private enum InterfaceState {
        case unavailable
        case owned
        case foreign
    }

    private let dataRoot = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Транскрибатор")
    private var instanceID = UUID().uuidString.lowercased()
    private let buildID =
        Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String
        ?? Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
        ?? "development"
    private var runtimeProcess: Process?
    private var logHandle: FileHandle?
    private var statusItem: NSStatusItem?
    private var startupTimer: Timer?
    private var startupAttempts = 0
    private var expectedRuntimePID: Int32?
    private var didStart = false
    private let interfaceURL = URL(string: "http://127.0.0.1:7860")!
    private var markerURL: URL {
        dataRoot.appendingPathComponent("runtime-instance.json")
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        start()
    }

    func start() {
        guard !didStart else { return }
        didStart = true
        configureMenuBar()
        if let marker = readRuntimeMarker(), marker.buildID == buildID {
            switch interfaceState(
                expectedInstanceID: marker.instanceID,
                expectedPID: marker.pid
            ) {
            case .owned:
                openInterface()
                return
            case .unavailable where processIsRunning(marker.pid):
                instanceID = marker.instanceID
                expectedRuntimePID = marker.pid
                scheduleRuntimePoll()
                return
            case .foreign:
                showError("Порт 7860 занят другим локальным процессом.")
                return
            case .unavailable:
                removeRuntimeMarker(ifMatching: marker)
            }
        }
        if interfaceState(
            expectedInstanceID: instanceID,
            expectedPID: nil
        ) == .foreign {
            showError("Порт 7860 занят другим локальным процессом.")
            return
        }
        do {
            try launchRuntime()
            scheduleRuntimePoll()
        } catch {
            showError(error.localizedDescription)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let process = runtimeProcess, process.isRunning {
            process.terminate()
            removeRuntimeMarker(
                ifMatching: RuntimeMarker(
                    buildID: buildID,
                    instanceID: instanceID,
                    pid: process.processIdentifier
                )
            )
        }
        try? logHandle?.close()
    }

    private func configureMenuBar() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        statusItem?.button?.title = "Т"
        statusItem?.button?.toolTip = "Транскрибатор"

        let menu = NSMenu()
        menu.addItem(
            withTitle: "Открыть транскрибатор",
            action: #selector(openInterfaceFromMenu),
            keyEquivalent: ""
        )
        menu.addItem(
            withTitle: "Открыть транскрипции",
            action: #selector(openOutputFolder),
            keyEquivalent: ""
        )
        menu.addItem(
            withTitle: "Лицензии и приватность",
            action: #selector(openLegalDocuments),
            keyEquivalent: ""
        )
        menu.addItem(NSMenuItem.separator())
        menu.addItem(
            withTitle: "О приложении",
            action: #selector(openAboutPanel),
            keyEquivalent: ""
        )
        menu.addItem(
            withTitle: "Завершить",
            action: #selector(quitApplication),
            keyEquivalent: "q"
        )
        menu.items.forEach { $0.target = self }
        statusItem?.menu = menu
    }

    private func launchRuntime() throws {
        guard
            let resources = Bundle.main.resourceURL,
            let executable = Bundle.main.executableURL
        else {
            throw productError("Не удалось определить ресурсы приложения.")
        }
        let runtime = resources
            .appendingPathComponent("runtime/transcriber-runtime/transcriber-runtime")
        guard FileManager.default.isExecutableFile(atPath: runtime.path) else {
            throw productError("В приложении не найден локальный runtime.")
        }

        let logs = dataRoot.appendingPathComponent("logs")
        try FileManager.default.createDirectory(
            at: logs,
            withIntermediateDirectories: true
        )
        let logURL = logs.appendingPathComponent("transcriber.log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        let handle = try FileHandle(forWritingTo: logURL)
        try handle.seekToEnd()
        logHandle = handle

        var environment = ProcessInfo.processInfo.environment
        environment["TRANSCRIBER_DATA_DIR"] = dataRoot.path
        environment["TRANSCRIBER_BUILD_ID"] = buildID
        environment["TRANSCRIBER_INSTANCE_ID"] = instanceID
        environment["TRANSCRIBER_GIGAAM_MODELS_DIR"] = resources
            .appendingPathComponent("models/gigaam").path
        environment["TRANSCRIBER_CAPTURE_HELPER"] = executable.path
        environment["HF_HOME"] = dataRoot
            .appendingPathComponent("models/huggingface").path
        environment["HF_HUB_DISABLE_TELEMETRY"] = "1"
        environment["PATH"] = [
            resources.appendingPathComponent("bin").path,
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ].joined(separator: ":")

        let process = Process()
        process.executableURL = runtime
        process.arguments = ["--no-browser"]
        process.environment = environment
        process.currentDirectoryURL = resources
        process.standardOutput = handle
        process.standardError = handle
        process.terminationHandler = { [weak self] process in
            Task { @MainActor in
                self?.removeRuntimeMarker(
                    ifMatching: RuntimeMarker(
                        buildID: self?.buildID ?? "",
                        instanceID: self?.instanceID ?? "",
                        pid: process.processIdentifier
                    )
                )
                guard process.terminationStatus != 0 else { return }
                self?.showError(
                    "Локальный процесс завершился с кодом \(process.terminationStatus). "
                    + "Откройте журнал приложения."
                )
            }
        }
        try process.run()
        runtimeProcess = process
        expectedRuntimePID = process.processIdentifier
        do {
            try writeRuntimeMarker(
                RuntimeMarker(
                    buildID: buildID,
                    instanceID: instanceID,
                    pid: process.processIdentifier
                )
            )
        } catch {
            process.terminate()
            runtimeProcess = nil
            throw error
        }
    }

    private func interfaceState(
        expectedInstanceID: String,
        expectedPID: Int32?
    ) -> InterfaceState {
        let descriptor = socket(AF_INET, SOCK_STREAM, 0)
        guard descriptor >= 0 else { return .unavailable }
        defer { close(descriptor) }

        var timeout = timeval(tv_sec: 0, tv_usec: 100_000)
        setsockopt(
            descriptor,
            SOL_SOCKET,
            SO_SNDTIMEO,
            &timeout,
            socklen_t(MemoryLayout<timeval>.size)
        )
        setsockopt(
            descriptor,
            SOL_SOCKET,
            SO_RCVTIMEO,
            &timeout,
            socklen_t(MemoryLayout<timeval>.size)
        )

        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(7_860).bigEndian
        guard inet_pton(AF_INET, "127.0.0.1", &address.sin_addr) == 1 else {
            return .unavailable
        }
        let connected = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(
                    descriptor,
                    $0,
                    socklen_t(MemoryLayout<sockaddr_in>.size)
                ) == 0
            }
        }
        guard connected else { return .unavailable }

        let request = "GET /api/health HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n"
        let sent = request.withCString {
            Darwin.send(descriptor, $0, strlen($0), 0)
        }
        guard sent == request.utf8.count else { return .foreign }

        var response = [UInt8](repeating: 0, count: 4_096)
        var responseData = Data()
        while responseData.count < 16_384 {
            let received = Darwin.recv(descriptor, &response, response.count, 0)
            guard received > 0 else { break }
            responseData.append(contentsOf: response.prefix(received))
        }
        guard
            !responseData.isEmpty,
            let text = String(data: responseData, encoding: .utf8),
            let separator = text.range(of: "\r\n\r\n")
        else {
            return .foreign
        }
        let header = String(text[..<separator.lowerBound])
        guard let statusLine = header.split(separator: "\r\n", maxSplits: 1).first else {
            return .foreign
        }
        let statusParts = statusLine.split(separator: " ")
        guard statusParts.count >= 2, statusParts[1] == "200" else {
            return .foreign
        }
        let body = Data(text[separator.upperBound...].utf8)
        let payload = try? JSONSerialization.jsonObject(with: body) as? [String: Any]
        let matchesPID =
            expectedPID.map { payload?["pid"] as? Int == Int($0) } ?? true
        guard
            let payload,
            payload["product"] as? String == "transcriber",
            payload["schema_version"] as? Int == 1,
            payload["build_id"] as? String == buildID,
            payload["instance_id"] as? String == expectedInstanceID,
            matchesPID
        else {
            return .foreign
        }
        return .owned
    }

    private func scheduleRuntimePoll() {
        startupTimer = Timer.scheduledTimer(
            timeInterval: 0.25,
            target: self,
            selector: #selector(pollRuntime),
            userInfo: nil,
            repeats: true
        )
    }

    private func readRuntimeMarker() -> RuntimeMarker? {
        guard
            let data = try? Data(contentsOf: markerURL),
            let marker = try? JSONDecoder().decode(RuntimeMarker.self, from: data)
        else {
            return nil
        }
        return marker
    }

    private func writeRuntimeMarker(_ marker: RuntimeMarker) throws {
        try FileManager.default.createDirectory(
            at: dataRoot,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        let data = try JSONEncoder().encode(marker)
        try data.write(to: markerURL, options: .atomic)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: markerURL.path
        )
    }

    private func removeRuntimeMarker(ifMatching expected: RuntimeMarker) {
        guard let marker = readRuntimeMarker(), marker.pid == expected.pid,
              marker.buildID == expected.buildID,
              marker.instanceID == expected.instanceID
        else {
            return
        }
        try? FileManager.default.removeItem(at: markerURL)
    }

    private func processIsRunning(_ pid: Int32) -> Bool {
        guard pid > 0 else { return false }
        return kill(pid, 0) == 0 || errno == EPERM
    }

    private func openInterface() {
        NSWorkspace.shared.open(interfaceURL)
    }

    private func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Не удалось запустить транскрибатор"
        alert.informativeText = message
        alert.alertStyle = .critical
        alert.addButton(withTitle: "Понятно")
        alert.runModal()
    }

    private func productError(_ message: String) -> NSError {
        NSError(
            domain: Bundle.main.bundleIdentifier ?? "Transcriber",
            code: 1,
            userInfo: [NSLocalizedDescriptionKey: message]
        )
    }

    @objc private func openInterfaceFromMenu() {
        openInterface()
    }

    @objc private func pollRuntime() {
        startupAttempts += 1
        switch interfaceState(
            expectedInstanceID: instanceID,
            expectedPID: expectedRuntimePID
        ) {
        case .owned:
            startupTimer?.invalidate()
            startupTimer = nil
            openInterface()
        case .foreign:
            startupTimer?.invalidate()
            startupTimer = nil
            showError("Порт 7860 занят другим локальным процессом.")
        case .unavailable where startupAttempts >= 80:
            startupTimer?.invalidate()
            startupTimer = nil
            showError("Локальный интерфейс не запустился. Проверьте журнал приложения.")
        case .unavailable:
            break
        }
    }

    @objc private func openOutputFolder() {
        let output = dataRoot.appendingPathComponent("output")
        try? FileManager.default.createDirectory(
            at: output,
            withIntermediateDirectories: true
        )
        NSWorkspace.shared.open(output)
    }

    @objc private func openLegalDocuments() {
        guard let resources = Bundle.main.resourceURL else { return }
        NSWorkspace.shared.open(resources.appendingPathComponent("Лицензии"))
    }

    @objc private func openAboutPanel() {
        NSApplication.shared.orderFrontStandardAboutPanel(nil)
    }

    @objc private func quitApplication() {
        NSApplication.shared.terminate(nil)
    }
}

final class EventWriter: @unchecked Sendable {
    private let queue = DispatchQueue(label: "transcriber.capture.events")
    private var detectedOutputs = Set<String>()

    func send(_ event: String, extra: [String: Any] = [:]) {
        queue.sync {
            var payload = extra
            payload["event"] = event
            guard
                let data = try? JSONSerialization.data(withJSONObject: payload),
                let newline = "\n".data(using: .utf8)
            else {
                return
            }
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(newline)
        }
    }

    func reportAudio(for output: String, byteCount: Int) {
        queue.sync {
            guard detectedOutputs.insert(output).inserted else {
                return
            }
            let payload: [String: Any] = [
                "event": "audio_detected",
                "source": output,
                "byte_count": byteCount,
                "sample_rate": 16_000,
                "channels": 1,
                "encoding": "pcm_s16le",
            ]
            guard
                let data = try? JSONSerialization.data(withJSONObject: payload),
                let newline = "\n".data(using: .utf8)
            else {
                return
            }
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(newline)
        }
    }

    func sendFailure(_ failure: CaptureFailure) {
        if let permissionState = failure.permissionState {
            send(
                "permission_state",
                extra: [
                    "source": failure.source,
                    "state": permissionState,
                ]
            )
        }
        var error: [String: Any] = [
            "source": failure.source,
            "state": "error",
            "error_code": failure.code,
            "error_domain": failure.domain,
            "retryable": failure.retryable,
            "message": failure.message,
        ]
        if let nativeCode = failure.nativeCode {
            error["native_code"] = nativeCode
        }
        send("error", extra: error)
    }
}

struct CaptureFailure: Error, LocalizedError, Sendable {
    let source: String
    let domain: String
    let code: String
    let nativeCode: Int?
    let permissionState: String?
    let retryable: Bool
    let message: String

    init(
        source: String,
        domain: String,
        code: String,
        nativeCode: Int? = nil,
        permissionState: String? = nil,
        retryable: Bool = false,
        message: String
    ) {
        self.source = source
        self.domain = domain
        self.code = code
        self.nativeCode = nativeCode
        self.permissionState = permissionState
        self.retryable = retryable
        self.message = message
    }

    var errorDescription: String? {
        message
    }
}

final class PCMWriter: @unchecked Sendable {
    private let outputFormat = AVAudioFormat(
        commonFormat: .pcmFormatInt16,
        sampleRate: 16_000,
        channels: 1,
        interleaved: true
    )!
    private let file: FileHandle
    private var converter: AVAudioConverter?
    private var inputFormat: AVAudioFormat?

    init(fileDescriptor: Int32) {
        file = FileHandle(fileDescriptor: fileDescriptor, closeOnDealloc: false)
    }

    func write(
        bufferList: UnsafePointer<AudioBufferList>,
        format: AVAudioFormat
    ) throws -> Int {
        guard let inputBuffer = AVAudioPCMBuffer(
            pcmFormat: format,
            bufferListNoCopy: bufferList,
            deallocator: nil
        ) else {
            return 0
        }
        return try write(inputBuffer)
    }

    func write(_ inputBuffer: AVAudioPCMBuffer) throws -> Int {
        let sourceFormat = inputBuffer.format
        let frameCount = inputBuffer.frameLength
        if inputFormat != sourceFormat {
            guard let newConverter = AVAudioConverter(
                from: sourceFormat,
                to: outputFormat
            ) else {
                throw NSError(
                    domain: "RealtimeCapture",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "Не удалось создать PCM-конвертер."]
                )
            }
            newConverter.downmix = true
            newConverter.sampleRateConverterQuality = AVAudioQuality.high.rawValue
            converter = newConverter
            inputFormat = sourceFormat
        }
        guard let converter else {
            return 0
        }

        let ratio = outputFormat.sampleRate / sourceFormat.sampleRate
        let capacity = AVAudioFrameCount(ceil(Double(frameCount) * ratio)) + 256
        guard let outputBuffer = AVAudioPCMBuffer(
            pcmFormat: outputFormat,
            frameCapacity: capacity
        ) else {
            return 0
        }

        var providedInput = false
        var conversionError: NSError?
        let status = converter.convert(
            to: outputBuffer,
            error: &conversionError
        ) { _, inputStatus in
            if providedInput {
                inputStatus.pointee = .noDataNow
                return nil
            }
            providedInput = true
            inputStatus.pointee = .haveData
            return inputBuffer
        }
        if let conversionError {
            throw conversionError
        }
        guard
            status == .haveData || status == .inputRanDry || status == .endOfStream,
            outputBuffer.frameLength > 0
        else {
            return 0
        }

        let audioBuffer = outputBuffer.mutableAudioBufferList.pointee.mBuffers
        guard let bytes = audioBuffer.mData else {
            return 0
        }
        let byteCount = Int(audioBuffer.mDataByteSize)
        file.write(Data(bytes: bytes, count: byteCount))
        return byteCount
    }
}

final class TerminationWaiter: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<CaptureFailure?, Never>?
    private var result: CaptureFailure?
    private var signaled = false
    private let interruptSource: DispatchSourceSignal
    private let terminateSource: DispatchSourceSignal

    init() {
        signal(SIGINT, SIG_IGN)
        signal(SIGTERM, SIG_IGN)
        interruptSource = DispatchSource.makeSignalSource(signal: SIGINT, queue: .global())
        terminateSource = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .global())
        interruptSource.setEventHandler { [weak self] in self?.finish() }
        terminateSource.setEventHandler { [weak self] in self?.finish() }
        interruptSource.resume()
        terminateSource.resume()
    }

    func wait() async -> CaptureFailure? {
        await withCheckedContinuation { continuation in
            lock.lock()
            if signaled {
                let result = self.result
                lock.unlock()
                continuation.resume(returning: result)
            } else {
                self.continuation = continuation
                lock.unlock()
            }
        }
    }

    func finish(with failure: CaptureFailure? = nil) {
        lock.lock()
        guard !signaled else {
            lock.unlock()
            return
        }
        signaled = true
        result = failure
        if let continuation {
            self.continuation = nil
            lock.unlock()
            continuation.resume(returning: failure)
        } else {
            lock.unlock()
        }
    }
}

final class MicrophoneCapture: @unchecked Sendable {
    private let engine = AVAudioEngine()
    private let writer: EventWriter
    private let pcm: PCMWriter
    private let onFailure: @Sendable (CaptureFailure) -> Void
    private var tapInstalled = false

    init(
        writer: EventWriter,
        fileDescriptor: Int32,
        onFailure: @escaping @Sendable (CaptureFailure) -> Void
    ) {
        self.writer = writer
        pcm = PCMWriter(fileDescriptor: fileDescriptor)
        self.onFailure = onFailure
    }

    func start() async throws {
        let authorization = AVCaptureDevice.authorizationStatus(for: .audio)
        let granted: Bool
        switch authorization {
        case .authorized:
            granted = true
        case .notDetermined:
            granted = await withCheckedContinuation { continuation in
                AVCaptureDevice.requestAccess(for: .audio) { allowed in
                    continuation.resume(returning: allowed)
                }
            }
        case .denied, .restricted:
            granted = false
        @unknown default:
            granted = false
        }
        guard granted else {
            let restricted = authorization == .restricted
            throw CaptureFailure(
                source: "microphone",
                domain: "AVFoundation",
                code: restricted ? "permission_restricted" : "permission_denied",
                nativeCode: Int(authorization.rawValue),
                permissionState: "denied",
                retryable: !restricted,
                message: "Нет разрешения на доступ к микрофону."
            )
        }

        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw CaptureFailure(
                source: "microphone",
                domain: "AVFoundation",
                code: "device_unavailable",
                nativeCode: 1,
                permissionState: "unavailable",
                retryable: true,
                message: "Микрофон не предоставил поддерживаемый аудиоформат."
            )
        }
        input.installTap(onBus: 0, bufferSize: 4_096, format: format) {
            [writer, pcm, onFailure] buffer, _ in
            do {
                let count = try pcm.write(buffer)
                if count > 0 {
                    writer.reportAudio(for: "microphone", byteCount: count)
                }
            } catch {
                onFailure(
                    CaptureFailure(
                        source: "microphone",
                        domain: (error as NSError).domain,
                        code: "capture_failed",
                        nativeCode: (error as NSError).code,
                        message: error.localizedDescription
                    )
                )
            }
        }
        tapInstalled = true
        engine.prepare()
        do {
            try engine.start()
        } catch {
            stop()
            throw CaptureFailure(
                source: "microphone",
                domain: (error as NSError).domain,
                code: "device_unavailable",
                nativeCode: (error as NSError).code,
                permissionState: "unavailable",
                retryable: true,
                message: error.localizedDescription
            )
        }
    }

    func stop() {
        if tapInstalled {
            engine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
        if engine.isRunning {
            engine.stop()
        }
    }
}

final class SystemAudioCapture: @unchecked Sendable {
    private let writer: EventWriter
    private let pcm: PCMWriter
    private let onFailure: @Sendable (CaptureFailure) -> Void
    private let ioQueue = DispatchQueue(label: "transcriber.capture.system")
    private var tapID = AudioObjectID(kAudioObjectUnknown)
    private var aggregateID = AudioObjectID(kAudioObjectUnknown)
    private var ioProcID: AudioDeviceIOProcID?
    private var started = false

    init(
        writer: EventWriter,
        fileDescriptor: Int32,
        onFailure: @escaping @Sendable (CaptureFailure) -> Void
    ) {
        self.writer = writer
        pcm = PCMWriter(fileDescriptor: fileDescriptor)
        self.onFailure = onFailure
    }

    func start() throws {
        let tapDescription = CATapDescription(monoGlobalTapButExcludeProcesses: [])
        tapDescription.name = "Транскрибатор — системный звук"
        tapDescription.isPrivate = true
        tapDescription.muteBehavior = .unmuted

        var status = AudioHardwareCreateProcessTap(tapDescription, &tapID)
        guard status == noErr else {
            throw coreAudioFailure(status, operation: "создать системный аудиопоток")
        }

        do {
            let tapUID = try readTapUID()
            var streamDescription = try readTapFormat()
            guard let inputFormat = AVAudioFormat(streamDescription: &streamDescription) else {
                throw CaptureFailure(
                    source: "system",
                    domain: "CoreAudio",
                    code: "device_unavailable",
                    nativeCode: 1,
                    permissionState: "unavailable",
                    retryable: true,
                    message: "Core Audio Tap не предоставил поддерживаемый формат."
                )
            }

            let aggregateDescription: [String: Any] = [
                "name": "Транскрибатор — системный звук",
                "uid": "ru.transcriber.capture.\(UUID().uuidString)",
                "private": true,
                "tapautostart": false,
                "taps": [
                    [
                        "uid": tapUID,
                        "drift": true,
                    ],
                ],
            ]
            status = AudioHardwareCreateAggregateDevice(
                aggregateDescription as CFDictionary,
                &aggregateID
            )
            guard status == noErr else {
                throw coreAudioFailure(status, operation: "создать приватное aggregate-устройство")
            }

            status = AudioDeviceCreateIOProcIDWithBlock(
                &ioProcID,
                aggregateID,
                ioQueue
            ) { [writer, pcm, onFailure] _, inputData, _, _, _ in
                guard inputData.pointee.mNumberBuffers > 0 else {
                    return
                }
                do {
                    let count = try pcm.write(bufferList: inputData, format: inputFormat)
                    if count > 0 {
                        writer.reportAudio(for: "system", byteCount: count)
                    }
                } catch {
                    onFailure(
                        CaptureFailure(
                            source: "system",
                            domain: (error as NSError).domain,
                            code: "capture_failed",
                            nativeCode: (error as NSError).code,
                            message: error.localizedDescription
                        )
                    )
                }
            }
            guard status == noErr, let ioProcID else {
                throw coreAudioFailure(status, operation: "создать callback системного звука")
            }

            status = AudioDeviceStart(aggregateID, ioProcID)
            guard status == noErr else {
                throw coreAudioFailure(status, operation: "запустить системный аудиопоток")
            }
            started = true
        } catch {
            stop()
            throw error
        }
    }

    func stop() {
        if started, let ioProcID {
            AudioDeviceStop(aggregateID, ioProcID)
            started = false
        }
        if let ioProcID, aggregateID != kAudioObjectUnknown {
            AudioDeviceDestroyIOProcID(aggregateID, ioProcID)
            self.ioProcID = nil
        }
        if aggregateID != kAudioObjectUnknown {
            AudioHardwareDestroyAggregateDevice(aggregateID)
            aggregateID = AudioObjectID(kAudioObjectUnknown)
        }
        if tapID != kAudioObjectUnknown {
            AudioHardwareDestroyProcessTap(tapID)
            tapID = AudioObjectID(kAudioObjectUnknown)
        }
    }

    private func readTapUID() throws -> CFString {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioTapPropertyUID,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var value: Unmanaged<CFString>?
        var size = UInt32(MemoryLayout<Unmanaged<CFString>?>.size)
        let status = AudioObjectGetPropertyData(
            tapID,
            &address,
            0,
            nil,
            &size,
            &value
        )
        guard status == noErr else {
            throw coreAudioFailure(status, operation: "прочитать свойства Core Audio Tap")
        }
        guard let value else {
            throw CaptureFailure(
                source: "system",
                domain: "CoreAudio",
                code: "capture_failed",
                nativeCode: 1,
                message: "Core Audio Tap не предоставил UID."
            )
        }
        return value.takeRetainedValue()
    }

    private func readTapFormat() throws -> AudioStreamBasicDescription {
        var address = AudioObjectPropertyAddress(
            mSelector: kAudioTapPropertyFormat,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var value = AudioStreamBasicDescription()
        var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
        let status = AudioObjectGetPropertyData(
            tapID,
            &address,
            0,
            nil,
            &size,
            &value
        )
        guard status == noErr else {
            throw coreAudioFailure(status, operation: "прочитать формат Core Audio Tap")
        }
        return value
    }

    private func coreAudioFailure(_ status: OSStatus, operation: String) -> CaptureFailure {
        let permissionDenied = status == kAudioDevicePermissionsError
        return CaptureFailure(
            source: "system",
            domain: "CoreAudio",
            code: permissionDenied ? "permission_denied" : "capture_failed",
            nativeCode: Int(status),
            permissionState: permissionDenied ? "denied" : nil,
            retryable: true,
            message: "Не удалось \(operation) (OSStatus \(status))."
        )
    }
}

@main
enum RealtimeCapture {
    @MainActor
    static func main() async {
        let writer = EventWriter()

        do {
            let systemFD = fileDescriptor(named: "--system-fd")
            let microphoneFD = fileDescriptor(named: "--microphone-fd")
            if systemFD == nil && microphoneFD == nil {
                guard Bundle.main.bundleURL.pathExtension == "app" else {
                    writer.sendFailure(
                        CaptureFailure(
                            source: "lifecycle",
                            domain: "process.arguments",
                            code: "invalid_arguments",
                            nativeCode: 2,
                            message: "Не переданы локальные PCM-каналы."
                        )
                    )
                    Foundation.exit(2)
                }
                runProductApplication()
                return
            }
            guard let systemFD, let microphoneFD else {
                writer.sendFailure(
                    CaptureFailure(
                        source: "lifecycle",
                        domain: "process.arguments",
                        code: "invalid_arguments",
                        nativeCode: 2,
                        message: "Не переданы локальные PCM-каналы."
                    )
                )
                Foundation.exit(2)
            }
            if CommandLine.arguments.contains("--self-test") {
                try runSelfTest(
                    writer: writer,
                    systemFD: systemFD,
                    microphoneFD: microphoneFD
                )
                Foundation.exit(0)
            }
            let termination = TerminationWaiter()
            let microphoneCapture = MicrophoneCapture(
                writer: writer,
                fileDescriptor: microphoneFD
            ) { failure in
                termination.finish(with: failure)
            }
            let systemCapture = SystemAudioCapture(
                writer: writer,
                fileDescriptor: systemFD
            ) { failure in
                termination.finish(with: failure)
            }

            writer.send(
                "permission_state",
                extra: ["source": "microphone", "state": "requesting"]
            )
            try await microphoneCapture.start()
            writer.send(
                "permission_state",
                extra: ["source": "microphone", "state": "granted"]
            )
            do {
                writer.send(
                    "permission_state",
                    extra: ["source": "system", "state": "requesting"]
                )
                try systemCapture.start()
            } catch {
                microphoneCapture.stop()
                throw error
            }
            writer.send(
                "permission_state",
                extra: ["source": "system", "state": "granted"]
            )
            writer.send(
                "started",
                extra: [
                    "state": "capturing",
                    "pcm_sample_rate": 16_000,
                    "pcm_channels": 1,
                    "pcm_encoding": "pcm_s16le",
                ]
            )

            let runtimeFailure = await termination.wait()
            writer.send(
                "state",
                extra: ["source": "lifecycle", "state": "stopping"]
            )
            systemCapture.stop()
            microphoneCapture.stop()
            if let runtimeFailure {
                writer.sendFailure(runtimeFailure)
                Foundation.exit(1)
            }
            writer.send("stopped", extra: ["state": "idle"])
        } catch let failure as CaptureFailure {
            writer.sendFailure(failure)
            Foundation.exit(1)
        } catch {
            writer.sendFailure(
                CaptureFailure(
                    source: "lifecycle",
                    domain: (error as NSError).domain,
                    code: "capture_failed",
                    nativeCode: (error as NSError).code,
                    message: error.localizedDescription
                )
            )
            Foundation.exit(1)
        }
    }

    private static func fileDescriptor(named name: String) -> Int32? {
        guard
            let index = CommandLine.arguments.firstIndex(of: name),
            CommandLine.arguments.indices.contains(index + 1)
        else {
            return nil
        }
        return Int32(CommandLine.arguments[index + 1])
    }

    @MainActor
    private static func runProductApplication() {
        let application = NSApplication.shared
        let delegate = ProductApplicationDelegate()
        application.setActivationPolicy(.accessory)
        application.delegate = delegate
        objc_setAssociatedObject(
            application,
            "transcriber.delegate",
            delegate,
            .OBJC_ASSOCIATION_RETAIN_NONATOMIC
        )
        application.finishLaunching()
        delegate.start()
        application.run()
    }

    private static func runSelfTest(
        writer: EventWriter,
        systemFD: Int32,
        microphoneFD: Int32
    ) throws {
        let format = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: 48_000,
            channels: 1,
            interleaved: false
        )!
        let frames: AVAudioFrameCount = 4_800
        let makeBuffer: () -> AVAudioPCMBuffer = {
            let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames)!
            buffer.frameLength = frames
            if let channel = buffer.floatChannelData?[0] {
                for frame in 0..<Int(frames) {
                    channel[frame] = sin(Float(frame) * 0.03) * 0.25
                }
            }
            return buffer
        }
        let systemWriter = PCMWriter(fileDescriptor: systemFD)
        let microphoneWriter = PCMWriter(fileDescriptor: microphoneFD)
        let systemBytes =
            try systemWriter.write(makeBuffer()) + systemWriter.write(makeBuffer())
        let microphoneBytes =
            try microphoneWriter.write(makeBuffer()) + microphoneWriter.write(makeBuffer())
        writer.send(
            "self_test",
            extra: [
                "system_bytes": systemBytes,
                "microphone_bytes": microphoneBytes,
                "state": "self_test",
                "sample_rate": 16_000,
                "channels": 1,
                "encoding": "pcm_s16le",
            ]
        )
    }
}
