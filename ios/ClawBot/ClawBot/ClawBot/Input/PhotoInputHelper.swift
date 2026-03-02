import SwiftUI
import PhotosUI
import Foundation

// DESIGN DECISION: Images are sent as base64 via WebSocket in a 'vision.extract'
// request payload. This avoids adding a separate HTTP upload endpoint for MVP.
// Trade-off: WebSocket frames are larger, but simplifies architecture.
// Max image size after compression: 2MB.
// For production, consider a presigned S3 upload + reference URL approach.

// MARK: - PhotoUploadState

/// Upload state for tracking image processing.
enum PhotoUploadState: Equatable {
    case idle
    case processing
    case uploading
    case success
    case error(String)
}

// MARK: - PhotoInputHelper

/// Manages photo selection, compression, and sending to the gateway.
@MainActor
class PhotoInputHelper: ObservableObject {

    @Published var selectedItem: PhotosPickerItem?
    @Published var uploadState: PhotoUploadState = .idle
    @Published var previewImage: Image?

    private let webSocket: any WebSocketServiceProtocol
    private let maxImageBytes = 2 * 1024 * 1024  // 2MB after compression
    private let maxDimension: CGFloat = 2048

    init(webSocket: any WebSocketServiceProtocol) {
        self.webSocket = webSocket
    }

    /// Process a selected photo and send to gateway for vision extraction.
    /// - Parameters:
    ///   - item: The PhotosPickerItem from PhotosPicker
    ///   - hint: Optional hint about what to extract (e.g. "flight booking", "apartment listing")
    func processAndSend(item: PhotosPickerItem, hint: String? = nil) async {
        selectedItem = item
        uploadState = .processing

        // Step 1: Load image data from PhotosPicker
        guard let imageData = try? await loadImageData(from: item) else {
            uploadState = .error("Could not load image")
            return
        }

        // Step 2: Create UIImage for preview and processing
        guard let uiImage = UIImage(data: imageData) else {
            uploadState = .error("Invalid image format")
            return
        }

        // Set preview
        previewImage = Image(uiImage: uiImage)

        // Step 3: Resize if needed
        let resized = resizeIfNeeded(uiImage)

        // Step 4: Compress to JPEG
        guard let jpegData = compressToJPEG(resized) else {
            uploadState = .error("Failed to compress image")
            return
        }

        // Step 5: Convert to base64
        let base64String = jpegData.base64EncodedString()

        // Step 6: Send via WebSocket
        uploadState = .uploading
        sendVisionRequest(base64: base64String, hint: hint)

        uploadState = .success

        // Reset after brief delay
        try? await Task.sleep(nanoseconds: 2_000_000_000)
        reset()
    }

    /// Reset to idle state.
    func reset() {
        selectedItem = nil
        previewImage = nil
        uploadState = .idle
    }

    // MARK: - Private: Image Loading

    private func loadImageData(from item: PhotosPickerItem) async throws -> Data? {
        try await item.loadTransferable(type: Data.self)
    }

    // MARK: - Private: Resize

    /// Resize image so longest side is at most maxDimension pixels.
    private func resizeIfNeeded(_ image: UIImage) -> UIImage {
        let size = image.size
        let longest = max(size.width, size.height)

        guard longest > maxDimension else { return image }

        let scale = maxDimension / longest
        let newSize = CGSize(width: size.width * scale, height: size.height * scale)

        let renderer = UIGraphicsImageRenderer(size: newSize)
        return renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: newSize))
        }
    }

    // MARK: - Private: Compression

    /// Compress to JPEG, progressively reducing quality to stay under maxImageBytes.
    private func compressToJPEG(_ image: UIImage) -> Data? {
        var quality: CGFloat = 0.8
        let minQuality: CGFloat = 0.1

        while quality >= minQuality {
            if let data = image.jpegData(compressionQuality: quality) {
                if data.count <= maxImageBytes {
                    return data
                }
            }
            quality -= 0.1
        }

        // Last resort: lowest quality
        return image.jpegData(compressionQuality: minQuality)
    }

    // MARK: - Private: Send

    /// Build and send a vision.extract request. Uses synchronous send()
    /// matching WebSocketServiceProtocol (fire-and-forget).
    private func sendVisionRequest(base64: String, hint: String?) {
        var payload: [String: AnyCodable] = [
            "image_base64": AnyCodable(base64)
        ]
        if let hint {
            payload["hint"] = AnyCodable(hint)
        }

        let msg = WSMessage.request(
            method: "vision.extract",
            id: UUID().uuidString,
            payload: payload
        )
        webSocket.send(msg)
    }
}

// MARK: - PhotoInputView

/// SwiftUI view component with photo picker button and upload status.
/// Drop this into the chat input bar or wherever photo input is needed.
struct PhotoInputView: View {
    @ObservedObject var helper: PhotoInputHelper
    @State private var showPicker = false

    var body: some View {
        VStack(spacing: 8) {
            // Preview (if image selected)
            if let preview = helper.previewImage {
                preview
                    .resizable()
                    .scaledToFit()
                    .frame(maxHeight: 200)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                    .overlay(alignment: .topTrailing) {
                        Button(action: { helper.reset() }) {
                            Image(systemName: "xmark.circle.fill")
                                .font(.title3)
                                .foregroundStyle(.white)
                                .shadow(radius: 2)
                        }
                        .padding(8)
                    }
            }

            // Status indicator
            switch helper.uploadState {
            case .idle:
                EmptyView()
            case .processing:
                HStack(spacing: 6) {
                    ProgressView()
                        .controlSize(.small)
                    Text("Processing image...")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            case .uploading:
                HStack(spacing: 6) {
                    ProgressView()
                        .controlSize(.small)
                    Text("Sending to ClawBot...")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            case .success:
                HStack(spacing: 4) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    Text("Sent!")
                        .font(.caption)
                        .foregroundStyle(.green)
                }
            case .error(let msg):
                HStack(spacing: 4) {
                    Image(systemName: "exclamationmark.circle.fill")
                        .foregroundStyle(.red)
                    Text(msg)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }

            // Photo picker button
            let isIdle = helper.uploadState == .idle
            PhotosPicker(
                selection: Binding(
                    get: { helper.selectedItem },
                    set: { item in
                        if let item {
                            Task { await helper.processAndSend(item: item) }
                        }
                    }
                ),
                matching: .images,
                photoLibrary: .shared()
            ) {
                Image(systemName: "photo.on.rectangle.angled")
                    .font(.title3)
                    .foregroundStyle(isIdle ? .blue : .gray)
            }
            .disabled(!isIdle)
        }
    }
}

// MARK: - Previews

#Preview("Idle state") {
    PhotoInputView(helper: PhotoInputHelper(webSocket: MockWebSocketService()))
        .padding()
}
