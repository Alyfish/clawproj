import ActivityKit
import SwiftUI
import WidgetKit

// MARK: - Activity Attributes

struct ClawBotActivityAttributes: ActivityAttributes {
    let taskId: String
    let goalText: String

    struct ContentState: Codable, Hashable {
        let status: String        // "running", "completed", "stopped", "error", "waiting"
        let currentStep: String
        let stepCount: Int
        let totalSteps: Int
    }
}

// MARK: - Lock Screen / Banner View

struct ClawBotLockScreenView: View {
    let context: ActivityViewContext<ClawBotActivityAttributes>

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: "brain.head.profile")
                    .font(.title3)
                    .foregroundStyle(.blue)

                Text(context.attributes.goalText)
                    .font(.headline)
                    .lineLimit(1)

                Spacer()

                Text(context.state.status.capitalized)
                    .font(.caption)
                    .fontWeight(.semibold)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(statusColor(context.state.status).opacity(0.2))
                    .foregroundStyle(statusColor(context.state.status))
                    .clipShape(Capsule())
            }

            Text(context.state.currentStep)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .lineLimit(1)

            ProgressView(
                value: Double(context.state.stepCount),
                total: Double(max(context.state.totalSteps, 1))
            )
            .tint(statusColor(context.state.status))
        }
        .padding()
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "completed": return .green
        case "stopped", "error": return .red
        case "waiting": return .orange
        default: return .blue
        }
    }
}

// MARK: - Dynamic Island: Compact Leading

struct ClawBotCompactLeading: View {
    let context: ActivityViewContext<ClawBotActivityAttributes>

    var body: some View {
        Image(systemName: "brain.head.profile")
            .foregroundStyle(.blue)
    }
}

// MARK: - Dynamic Island: Compact Trailing

struct ClawBotCompactTrailing: View {
    let context: ActivityViewContext<ClawBotActivityAttributes>

    var body: some View {
        Text("\(context.state.stepCount)/\(context.state.totalSteps)")
            .font(.caption)
            .fontWeight(.medium)
            .monospacedDigit()
    }
}

// MARK: - Dynamic Island: Expanded View

struct ClawBotExpandedView: View {
    let context: ActivityViewContext<ClawBotActivityAttributes>

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(context.attributes.goalText)
                    .font(.headline)
                    .lineLimit(1)

                Spacer()

                Text(context.state.status.capitalized)
                    .font(.caption2)
                    .fontWeight(.semibold)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(statusColor(context.state.status).opacity(0.2))
                    .foregroundStyle(statusColor(context.state.status))
                    .clipShape(Capsule())
            }

            Text(context.state.currentStep)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .lineLimit(1)

            ProgressView(
                value: Double(context.state.stepCount),
                total: Double(max(context.state.totalSteps, 1))
            )
            .tint(statusColor(context.state.status))
        }
        .padding()
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "completed": return .green
        case "stopped", "error": return .red
        case "waiting": return .orange
        default: return .blue
        }
    }
}

// MARK: - Dynamic Island: Minimal View

struct ClawBotMinimalView: View {
    let context: ActivityViewContext<ClawBotActivityAttributes>

    var body: some View {
        Image(systemName: "brain.head.profile")
            .foregroundStyle(.blue)
    }
}
