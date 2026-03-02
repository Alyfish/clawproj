import SwiftUI

/// Chat bubble that renders assistant messages with full markdown and user messages
/// as plain text in a blue rounded rect.
struct MessageBubbleView: View {
    let message: ChatMessage

    var body: some View {
        HStack {
            if message.role == .user {
                Spacer(minLength: 60)
            }

            Group {
                if message.role == .assistant {
                    if message.isStreaming && message.content.isEmpty {
                        ProgressView()
                            .controlSize(.small)
                            .padding(12)
                    } else {
                        MarkdownContentView(message.content, foregroundColor: Color(.label))
                            .font(.system(size: 17))
                            .textSelection(.enabled)
                    }
                } else {
                    Text(message.content)
                        .font(.system(size: 17))
                        .foregroundStyle(.white)
                }
            }
            .padding(message.role == .user ? 12 : 0)
            .background(
                message.role == .user
                    ? RoundedRectangle(cornerRadius: 18)
                        .fill(Color.blue)
                    : nil
            )
            .contextMenu {
                Button {
                    UIPasteboard.general.string = message.content
                } label: {
                    Label("Copy", systemImage: "doc.on.doc")
                }
            }

            if message.role == .assistant {
                Spacer(minLength: 0)
            }
        }
    }
}

#Preview("User bubble") {
    MessageBubbleView(message: ChatMessage(role: .user, content: "Find me a flight to NYC"))
        .padding()
}

#Preview("Assistant bubble") {
    MessageBubbleView(message: ChatMessage(
        role: .assistant,
        content: "Here are **3 options** for flights:\n\n1. Delta — $320\n2. JetBlue — $289\n3. United — $305\n\n> All prices include taxes."
    ))
    .padding()
}

#Preview("Streaming empty") {
    MessageBubbleView(message: ChatMessage.assistantPlaceholder())
        .padding()
}
