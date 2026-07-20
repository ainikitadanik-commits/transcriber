import AppKit
import AVFoundation
import CoreMedia
import Darwin
import Foundation
@preconcurrency import ScreenCaptureKit

@MainActor
final class ProductApplicationDelegate: NSObject, NSApplicationDelegate {
    private let dataRoot = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Транскрибатор")
    private var runtimeProcess: Process?
    private var logHandle: FileHandle?
    private var statusItem: NSStatusItem?
    private var startupTimer: Timer?
    private var startupAttempts = 0
    private var didStart = false
    private let interfaceURL = URL(string: "http://127.0.0.1:7860")!

    func applicationDidFinishLaunching(_ notification: Notification) {
        start()
    }

    func start() {
        guard !didStart else { return }
        didStart = true
        configureMenuBar()
        if interfaceIsAvailable() {
            openInterface()
            return
        }
        do {
            try launchRuntime()
            startupTimer = Timer.scheduledTimer(
                timeInterval: 0.25,
                target: self,
                selector: #selector(pollRuntime),
                userInfo: nil,
                repeats: true
            )
        } catch {
            showError(error.localizedDescription)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let process = runtimeProcess, process.isRunning {
            process.terminate()
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
                guard process.terminationStatus != 0 else { return }
                self?.showError(
                    "Локальный процесс завершился с кодом \(process.terminationStatus). "
                    + "Откройте журнал приложения."
                )
            }
        }
        try process.run()
        runtimeProcess = process
    }

    private func interfaceIsAvailable() -> Bool {
        let descriptor = socket(AF_INET, SOCK_STREAM, 0)
        guard descriptor >= 0 else { return false }
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
            return false
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
        guard connected else { return false }

        let request = "GET /api/realtime/status HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n"
        let sent = request.withCString {
            Darwin.send(descriptor, $0, strlen($0), 0)
        }
        guard sent == request.utf8.count else { return false }

        var response = [UInt8](repeating: 0, count: 4_096)
        let received = Darwin.recv(descriptor, &response, response.count, 0)
        guard
            received > 0,
            let text = String(bytes: response.prefix(received), encoding: .utf8)
        else {
            return false
        }
        return text.contains(" 200 ") && text.contains("\"audio_format\"")
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
        if interfaceIsAvailable() {
            startupTimer?.invalidate()
            startupTimer = nil
            openInterface()
        } else if startupAttempts >= 80 {
            startupTimer?.invalidate()
            startupTimer = nil
            showError("Локальный интерфейс не запустился. Проверьте журнал приложения.")
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
}

final class PCMWriter {
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

    func write(_ sampleBuffer: CMSampleBuffer) throws -> Int {
        guard
            CMSampleBufferDataIsReady(sampleBuffer),
            let formatDescription = sampleBuffer.formatDescription
        else {
            return 0
        }
        let sourceFormat = AVAudioFormat(cmAudioFormatDescription: formatDescription)

        let frameCount = AVAudioFrameCount(sampleBuffer.numSamples)
        guard
            frameCount > 0,
            let inputBuffer = AVAudioPCMBuffer(
                pcmFormat: sourceFormat,
                frameCapacity: frameCount
            )
        else {
            return 0
        }
        inputBuffer.frameLength = frameCount
        try sampleBuffer.copyPCMData(
            fromRange: 0..<Int(frameCount),
            into: inputBuffer.mutableAudioBufferList
        )
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

final class CaptureReceiver: NSObject, SCStreamOutput, SCStreamDelegate {
    private let writer: EventWriter
    private let systemPCM: PCMWriter
    private let microphonePCM: PCMWriter

    init(writer: EventWriter, systemFD: Int32, microphoneFD: Int32) {
        self.writer = writer
        systemPCM = PCMWriter(fileDescriptor: systemFD)
        microphonePCM = PCMWriter(fileDescriptor: microphoneFD)
    }

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of outputType: SCStreamOutputType
    ) {
        do {
            switch outputType {
            case .audio:
                let count = try systemPCM.write(sampleBuffer)
                if count > 0 {
                    writer.reportAudio(for: "system", byteCount: count)
                }
            case .microphone:
                let count = try microphonePCM.write(sampleBuffer)
                if count > 0 {
                    writer.reportAudio(for: "microphone", byteCount: count)
                }
            default:
                break
            }
        } catch {
            writer.send("error", extra: ["message": error.localizedDescription])
        }
    }

    func stream(_ stream: SCStream, didStopWithError error: any Error) {
        writer.send("error", extra: ["message": error.localizedDescription])
    }
}

final class TerminationWaiter: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Void, Never>?
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

    func wait() async {
        await withCheckedContinuation { continuation in
            lock.lock()
            if signaled {
                lock.unlock()
                continuation.resume()
            } else {
                self.continuation = continuation
                lock.unlock()
            }
        }
    }

    private func finish() {
        lock.lock()
        if let continuation {
            self.continuation = nil
            lock.unlock()
            continuation.resume()
        } else {
            signaled = true
            lock.unlock()
        }
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
                    writer.send(
                        "error",
                        extra: ["message": "Не переданы локальные PCM-каналы."]
                    )
                    Foundation.exit(2)
                }
                runProductApplication()
                return
            }
            guard let systemFD, let microphoneFD else {
                writer.send("error", extra: ["message": "Не переданы локальные PCM-каналы."])
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
            let content = try await SCShareableContent.excludingDesktopWindows(
                false,
                onScreenWindowsOnly: true
            )
            guard let display = content.displays.first else {
                writer.send("error", extra: ["message": "Не найден доступный экран."])
                Foundation.exit(2)
            }

            let filter = SCContentFilter(
                display: display,
                excludingApplications: [],
                exceptingWindows: []
            )
            let configuration = SCStreamConfiguration()
            configuration.width = 2
            configuration.height = 2
            configuration.showsCursor = false
            configuration.minimumFrameInterval = CMTime(value: 1, timescale: 1)
            configuration.capturesAudio = true
            configuration.captureMicrophone = true
            configuration.excludesCurrentProcessAudio = true
            configuration.sampleRate = 48_000
            configuration.channelCount = 1

            let receiver = CaptureReceiver(
                writer: writer,
                systemFD: systemFD,
                microphoneFD: microphoneFD
            )
            let stream = SCStream(
                filter: filter,
                configuration: configuration,
                delegate: receiver
            )
            let systemQueue = DispatchQueue(label: "transcriber.capture.system")
            let microphoneQueue = DispatchQueue(label: "transcriber.capture.microphone")
            try stream.addStreamOutput(receiver, type: .audio, sampleHandlerQueue: systemQueue)
            try stream.addStreamOutput(
                receiver,
                type: .microphone,
                sampleHandlerQueue: microphoneQueue
            )

            try await stream.startCapture()
            writer.send(
                "started",
                extra: [
                    "sample_rate": configuration.sampleRate,
                    "channels": configuration.channelCount,
                    "pcm_sample_rate": 16_000,
                    "pcm_channels": 1,
                    "pcm_encoding": "pcm_s16le",
                ]
            )

            let termination = TerminationWaiter()
            await termination.wait()

            try await stream.stopCapture()
            writer.send("stopped")
        } catch {
            writer.send("error", extra: ["message": error.localizedDescription])
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
                "sample_rate": 16_000,
                "channels": 1,
                "encoding": "pcm_s16le",
            ]
        )
    }
}
