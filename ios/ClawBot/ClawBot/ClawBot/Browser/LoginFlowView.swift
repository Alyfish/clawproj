import SwiftUI

// MARK: - LoginFlowView

struct LoginFlowView: View {
    @ObservedObject var viewModel: LoginFlowViewModel
    @Environment(\.dismiss) private var dismiss

    // The browser viewport is 1280x720 (set in CDPBrowserTool.VIEWPORT)
    private let browserViewport = CGSize(width: 1280, height: 720)

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Status bar
                statusBar

                // Browser screenshot with element overlays
                GeometryReader { geo in
                    screenshotView(in: geo.size)
                }

                // Text input (visible when an input element is selected)
                if viewModel.selectedRef != nil {
                    inputBar
                }
            }
            .background(Color(.systemBackground))
            .navigationTitle("Browser Login")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        viewModel.done()
                        dismiss()
                    }
                    .fontWeight(.semibold)
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
            }
        }
    }

    // MARK: - Status bar

    private var statusBar: some View {
        HStack {
            Image(systemName: "lock.shield.fill")
                .foregroundStyle(.orange)
            Text(viewModel.statusMessage)
                .font(.caption)
                .lineLimit(1)
            Spacer()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.ultraThinMaterial)
    }

    // MARK: - Screenshot + overlays

    @ViewBuilder
    private func screenshotView(in size: CGSize) -> some View {
        if let image = viewModel.currentImage {
            let imageSize = image.size
            // Scale factor: fit image width to container
            let scale = size.width / imageSize.width
            let scaledHeight = imageSize.height * scale

            ScrollView(.vertical, showsIndicators: true) {
                ZStack(alignment: .topLeading) {
                    Image(uiImage: image)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: size.width, height: scaledHeight)

                    // Element overlays
                    ForEach(viewModel.elements) { element in
                        elementOverlay(element, scale: scale)
                    }
                }
                .frame(width: size.width, height: scaledHeight)
            }
        } else {
            VStack {
                ProgressView()
                Text("Waiting for browser...")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    // MARK: - Element overlay

    private func elementOverlay(_ element: LoginElement, scale: CGFloat) -> some View {
        let x = element.rect.origin.x * scale
        let y = element.rect.origin.y * scale
        let w = element.rect.width * scale
        let h = element.rect.height * scale

        let isInput = element.tag == "input" || element.tag == "textarea"
        let isSelected = viewModel.selectedRef == element.id

        return Button {
            if isInput {
                viewModel.selectedRef = element.id
            } else {
                viewModel.sendClick(ref: element.id)
            }
        } label: {
            ZStack(alignment: .topLeading) {
                RoundedRectangle(cornerRadius: 3)
                    .stroke(isSelected ? Color.blue : Color.orange.opacity(0.6), lineWidth: isSelected ? 2 : 1)
                    .background(
                        RoundedRectangle(cornerRadius: 3)
                            .fill(isInput ? Color.blue.opacity(0.08) : Color.orange.opacity(0.05))
                    )

                // Ref number badge
                Text("\(element.id)")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 3)
                    .padding(.vertical, 1)
                    .background(Capsule().fill(isInput ? Color.blue : Color.orange))
                    .offset(x: -4, y: -8)
            }
        }
        .frame(width: max(w, 20), height: max(h, 16))
        .offset(x: x, y: y)
        .buttonStyle(.plain)
    }

    // MARK: - Input bar

    private var inputBar: some View {
        HStack(spacing: 8) {
            if let ref = viewModel.selectedRef,
               let element = viewModel.elements.first(where: { $0.id == ref }) {
                Text("[\(ref)] \(element.text)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            TextField("Type here...", text: $viewModel.inputText)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.send)
                .onSubmit {
                    if let ref = viewModel.selectedRef, !viewModel.inputText.isEmpty {
                        viewModel.sendInput(ref: ref, text: viewModel.inputText)
                    }
                }

            Button {
                if let ref = viewModel.selectedRef, !viewModel.inputText.isEmpty {
                    viewModel.sendInput(ref: ref, text: viewModel.inputText)
                }
            } label: {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.title2)
                    .foregroundStyle(.blue)
            }
            .disabled(viewModel.inputText.isEmpty || viewModel.selectedRef == nil)

            Button {
                viewModel.selectedRef = nil
                viewModel.inputText = ""
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.ultraThinMaterial)
    }
}
