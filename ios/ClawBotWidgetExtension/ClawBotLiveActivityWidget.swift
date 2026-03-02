import ActivityKit
import SwiftUI
import WidgetKit

struct ClawBotLiveActivityWidget: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: ClawBotActivityAttributes.self) { context in
            // Lock screen / banner presentation
            ClawBotLockScreenView(context: context)
        } dynamicIsland: { context in
            DynamicIsland {
                // Expanded view
                DynamicIslandExpandedRegion(.leading) {
                    Image(systemName: "brain.head.profile")
                        .font(.title2)
                        .foregroundStyle(.blue)
                }

                DynamicIslandExpandedRegion(.trailing) {
                    Text("\(context.state.stepCount)/\(context.state.totalSteps)")
                        .font(.caption)
                        .fontWeight(.semibold)
                        .monospacedDigit()
                }

                DynamicIslandExpandedRegion(.center) {
                    Text(context.attributes.goalText)
                        .font(.headline)
                        .lineLimit(1)
                }

                DynamicIslandExpandedRegion(.bottom) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(context.state.currentStep)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)

                        ProgressView(
                            value: Double(context.state.stepCount),
                            total: Double(max(context.state.totalSteps, 1))
                        )
                        .tint(statusColor(context.state.status))
                    }
                }
            } compactLeading: {
                ClawBotCompactLeading(context: context)
            } compactTrailing: {
                ClawBotCompactTrailing(context: context)
            } minimal: {
                ClawBotMinimalView(context: context)
            }
        }
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
