import SwiftUI

/// A single grey status line with a shimmer animation showing what the agent is
/// currently doing (e.g. "Thinking...", "Reading IDENTITY.md...").
/// Tap to open the full activity detail card.
struct ThinkingShimmerView: View {
    let label: String
    var onTap: () -> Void = {}

    @State private var shimmerPhase: CGFloat = -1

    var body: some View {
        HStack(spacing: 6) {
            // Pulsing dot
            Circle()
                .fill(Color(.systemGray3))
                .frame(width: 8, height: 8)
                .opacity(shimmerPhase > 0 ? 0.4 : 1.0)

            Text(label)
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(Color(.systemGray))
                .lineLimit(1)
                .overlay(shimmerOverlay)
                .mask(
                    Text(label)
                        .font(.system(size: 15, weight: .medium))
                        .lineLimit(1)
                )
        }
        .padding(.vertical, 6)
        .padding(.horizontal, 12)
        .contentShape(Rectangle())
        .onTapGesture { onTap() }
        .onAppear {
            withAnimation(
                .easeInOut(duration: 1.5)
                .repeatForever(autoreverses: true)
            ) {
                shimmerPhase = 1
            }
        }
    }

    private var shimmerOverlay: some View {
        GeometryReader { geo in
            LinearGradient(
                colors: [
                    Color(.systemGray).opacity(0.3),
                    Color(.systemGray).opacity(0.7),
                    Color(.systemGray).opacity(0.3)
                ],
                startPoint: .leading,
                endPoint: .trailing
            )
            .frame(width: geo.size.width * 0.6)
            .offset(x: shimmerPhase * geo.size.width * 0.7)
        }
    }
}

#Preview {
    VStack(spacing: 20) {
        ThinkingShimmerView(label: "Thinking...")
        ThinkingShimmerView(label: "Reading IDENTITY.md...")
        ThinkingShimmerView(label: "Writing USER.md...")
    }
    .padding()
}
