import SwiftUI

// MARK: - ChatView

struct ChatView: View {

    @StateObject private var viewModel: ChatViewModel
    @State private var inputText = ""
    @State private var isAtBottom = true
    @FocusState private var isInputFocused: Bool
    @Environment(\.scenePhase) private var scenePhase

    init(
        webSocket: any WebSocketServiceProtocol = WebSocketService(),
        serverURL: URL = URL(string: "ws://localhost:8080")!
    ) {
        _viewModel = StateObject(wrappedValue: ChatViewModel(
            webSocket: webSocket,
            serverURL: serverURL
        ))
    }

    var body: some View {
        ZStack(alignment: .top) {
            VStack(spacing: 0) {
                messagesList
                inputBar
            }

            // Header overlay
            ChatHeaderView(
                botName: "ClawBot",
                isOnline: viewModel.connectionState == .connected
            )
        }
        .task {
            await viewModel.loadMessages()
            viewModel.connect()
        }
        .onChange(of: scenePhase) {
            if scenePhase == .active && viewModel.connectionState == .disconnected {
                viewModel.connect()
            }
        }
    }

    // MARK: - Messages list

    private var messagesList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 12) {
                    // Spacer for header overlay
                    Color.clear.frame(height: 72)

                    if viewModel.messages.isEmpty {
                        emptyState
                    } else {
                        ForEach(viewModel.messages) { message in
                            MessageBubbleView(message: message)
                                .id(message.id)
                        }
                    }

                    // Thinking steps inline
                    if viewModel.showThinkingSteps && !viewModel.thinkingSteps.isEmpty {
                        ThinkingStepsContainer(
                            steps: viewModel.thinkingSteps,
                            isVisible: viewModel.showThinkingSteps
                        )
                    }

                    // Shimmer view
                    if let shimmerLabel = viewModel.currentShimmerLabel {
                        ThinkingShimmerView(label: shimmerLabel)
                    }

                    // Bottom anchor
                    Color.clear
                        .frame(height: 1)
                        .id("bottom")
                        .onAppear { isAtBottom = true }
                        .onDisappear { isAtBottom = false }
                }
                .padding(.horizontal)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: viewModel.messages.count) {
                scrollToBottom(proxy: proxy)
            }
            .onChange(of: viewModel.currentShimmerLabel) {
                scrollToBottom(proxy: proxy)
            }
            .overlay(alignment: .bottomTrailing) {
                if !isAtBottom {
                    scrollToBottomButton {
                        withAnimation(.easeOut(duration: 0.2)) {
                            proxy.scrollTo("bottom", anchor: .bottom)
                        }
                    }
                    .padding(.trailing, 16)
                    .padding(.bottom, 8)
                    .transition(.scale.combined(with: .opacity))
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Spacer().frame(height: 100)
            Image(systemName: "bubble.left.and.bubble.right")
                .font(.system(size: 48))
                .foregroundStyle(.tertiary)
            Text("Start a conversation")
                .font(.headline)
                .foregroundStyle(.secondary)
            Text("Ask ClawBot to help with flights, apartments, documents, and more.")
                .font(.subheadline)
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Scroll-to-bottom FAB

    private func scrollToBottomButton(action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: "arrow.down.circle.fill")
                .font(.system(size: 32))
                .foregroundStyle(.blue)
                .background(Circle().fill(Color(.systemBackground)))
                .shadow(color: .black.opacity(0.15), radius: 4, y: 2)
        }
    }

    private func scrollToBottom(proxy: ScrollViewProxy) {
        withAnimation(.easeOut(duration: 0.2)) {
            proxy.scrollTo("bottom", anchor: .bottom)
        }
    }

    // MARK: - Input bar

    private var inputBar: some View {
        HStack(spacing: 8) {
            TextField("Message", text: $inputText, axis: .vertical)
                .textFieldStyle(.plain)
                .lineLimit(1...5)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    Capsule()
                        .fill(Color(.secondarySystemBackground))
                )
                .focused($isInputFocused)
                .onSubmit { sendMessage() }
                .disabled(viewModel.connectionState != .connected)

            Button(action: sendMessage) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 32))
                    .foregroundStyle(canSend ? .blue : Color(.systemGray4))
            }
            .disabled(!canSend)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.bar)
    }

    private var canSend: Bool {
        let trimmed = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty && !viewModel.isStreaming && viewModel.connectionState == .connected
    }

    // MARK: - Actions

    private func sendMessage() {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        inputText = ""
        viewModel.sendMessage(text)
    }
}

// MARK: - Previews

#Preview("Chat - Empty") {
    ChatView(webSocket: MockWebSocketService())
}

#Preview("Chat - Connected") {
    let mock = MockWebSocketService()
    ChatView(webSocket: mock)
        .onAppear {
            mock.simulateStateChange(.connected)
        }
}
