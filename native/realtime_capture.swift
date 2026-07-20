import CoreMedia
import Foundation
@preconcurrency import ScreenCaptureKit

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

    func reportSamples(for output: String, sampleBuffer: CMSampleBuffer) {
        guard CMSampleBufferDataIsReady(sampleBuffer) else {
            return
        }
        queue.sync {
            guard detectedOutputs.insert(output).inserted else {
                return
            }
            let payload: [String: Any] = [
                "event": "audio_detected",
                "source": output,
                "sample_count": CMSampleBufferGetNumSamples(sampleBuffer),
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

final class CaptureReceiver: NSObject, SCStreamOutput, SCStreamDelegate {
    private let writer: EventWriter

    init(writer: EventWriter) {
        self.writer = writer
    }

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of outputType: SCStreamOutputType
    ) {
        switch outputType {
        case .audio:
            writer.reportSamples(for: "system", sampleBuffer: sampleBuffer)
        case .microphone:
            writer.reportSamples(for: "microphone", sampleBuffer: sampleBuffer)
        default:
            break
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
    static func main() async {
        let writer = EventWriter()

        do {
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

            let receiver = CaptureReceiver(writer: writer)
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
}
