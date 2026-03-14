import SwiftUI

// MARK: - ThinkingStepPill

/// Pill/chip for a single thinking step — shows status icon + description.
struct ThinkingStepPill: View {
    let step: ThinkingStep

    var body: some View {
        HStack(spacing: 6) {
            statusIcon
            Text(step.description)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(backgroundColor)
        .clipShape(Capsule())
    }

    @ViewBuilder
    private var statusIcon: some View {
        switch step.status {
        case .pending:
            Image(systemName: "circle.dotted")
                .font(.caption)
                .foregroundStyle(.tertiary)
        case .running:
            ProgressView()
                .controlSize(.mini)
        case .done:
            Image(systemName: "checkmark.circle.fill")
                .font(.caption)
                .foregroundStyle(.green)
        case .error:
            Image(systemName: "exclamationmark.circle.fill")
                .font(.caption)
                .foregroundStyle(.red)
        }
    }

    private var backgroundColor: Color {
        switch step.status {
        case .pending: Color(.systemGray6)
        case .running: Color(.systemGray5)
        case .done:    Color(.systemGray6)
        case .error:   Color.red.opacity(0.1)
        }
    }
}

// MARK: - ThinkingStepsContainer

/// Displays multiple thinking step pills in a wrapping flow layout.
struct ThinkingStepsContainer: View {
    let steps: [ThinkingStep]
    var isVisible: Bool = true

    var body: some View {
        FlowLayout(spacing: 6) {
            ForEach(steps) { step in
                ThinkingStepPill(step: step)
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .opacity(isVisible ? 1 : 0)
        .animation(.easeOut(duration: 0.15), value: isVisible)
    }
}

// MARK: - FlowLayout

/// Custom layout that wraps children to the next line when they exceed available width.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = computeRows(proposal: proposal, subviews: subviews)
        guard !rows.isEmpty else { return .zero }

        let height = rows.reduce(CGFloat.zero) { total, row in
            total + row.height
        } + CGFloat(rows.count - 1) * spacing

        return CGSize(width: proposal.width ?? .zero, height: height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let rows = computeRows(proposal: proposal, subviews: subviews)
        var y = bounds.minY

        for row in rows {
            var x = bounds.minX
            for index in row.indices {
                let size = subviews[index].sizeThatFits(.unspecified)
                subviews[index].place(at: CGPoint(x: x, y: y), proposal: .unspecified)
                x += size.width + spacing
            }
            y += row.height + spacing
        }
    }

    // MARK: - Row computation

    private struct Row {
        var indices: [Int] = []
        var height: CGFloat = 0
    }

    private func computeRows(proposal: ProposedViewSize, subviews: Subviews) -> [Row] {
        let maxWidth = proposal.width ?? .infinity
        var rows: [Row] = []
        var currentRow = Row()
        var x: CGFloat = 0

        for (index, subview) in subviews.enumerated() {
            let size = subview.sizeThatFits(.unspecified)

            if !currentRow.indices.isEmpty && x + size.width > maxWidth {
                rows.append(currentRow)
                currentRow = Row()
                x = 0
            }

            currentRow.indices.append(index)
            currentRow.height = max(currentRow.height, size.height)
            x += size.width + spacing
        }

        if !currentRow.indices.isEmpty {
            rows.append(currentRow)
        }

        return rows
    }
}

// MARK: - CollapsibleStepsBadge

/// Compact badge showing step count. Tapping expands to reveal all step pills.
/// Auto-expands when errors are detected.
struct CollapsibleStepsBadge: View {
    let steps: [ThinkingStep]
    var currentLabel: String? = nil
    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            // Badge — always visible
            Button {
                withAnimation(.easeOut(duration: 0.2)) { isExpanded.toggle() }
            } label: {
                HStack(spacing: 6) {
                    if isRunning {
                        ProgressView()
                            .controlSize(.mini)
                    } else {
                        Image(systemName: "checkmark.circle.fill")
                            .font(.caption)
                            .foregroundStyle(.green)
                    }

                    Text(badgeLabel)
                        .font(.system(size: 14, weight: .medium))
                        .foregroundStyle(.secondary)

                    if errorCount > 0 {
                        Text("\(errorCount) error\(errorCount > 1 ? "s" : "")")
                            .font(.caption2)
                            .foregroundStyle(.red)
                    }

                    Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(Color(.systemGray6))
                .clipShape(Capsule())
            }
            .buttonStyle(.plain)

            // Expanded detail
            if isExpanded {
                ThinkingStepsContainer(steps: steps)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .onChange(of: errorCount) {
            if errorCount > 0 {
                withAnimation(.easeOut(duration: 0.2)) { isExpanded = true }
            }
        }
    }

    private var isRunning: Bool {
        steps.contains { $0.status == .running }
    }

    private var badgeLabel: String {
        if let label = currentLabel, isRunning {
            return "\(label) (\(steps.count) steps)"
        }
        return "Completed \(steps.count) steps"
    }

    private var errorCount: Int {
        steps.filter { $0.status == .error }.count
    }
}

// MARK: - Previews

#Preview("Running steps") {
    ThinkingStepsContainer(steps: [
        ThinkingStep(id: "1", description: "Searching flights", status: .running, timestamp: ""),
        ThinkingStep(id: "2", description: "Parsing results", status: .pending, timestamp: ""),
        ThinkingStep(id: "3", description: "Loaded user prefs", status: .done, timestamp: ""),
    ])
    .padding()
}

#Preview("Collapsible badge — running") {
    CollapsibleStepsBadge(
        steps: [
            ThinkingStep(id: "1", description: "Searching flights", status: .done, timestamp: ""),
            ThinkingStep(id: "2", description: "Parsing results", status: .running, timestamp: ""),
            ThinkingStep(id: "3", description: "Ranking options", status: .pending, timestamp: ""),
        ],
        currentLabel: "Parsing results"
    )
    .padding()
}

#Preview("Collapsible badge — done") {
    CollapsibleStepsBadge(
        steps: [
            ThinkingStep(id: "1", description: "Searched 3 sources", status: .done, timestamp: ""),
            ThinkingStep(id: "2", description: "Found 12 flights", status: .done, timestamp: ""),
            ThinkingStep(id: "3", description: "Created 3 cards", status: .done, timestamp: ""),
        ]
    )
    .padding()
}

#Preview("Collapsible badge — error") {
    CollapsibleStepsBadge(
        steps: [
            ThinkingStep(id: "1", description: "API call failed", status: .error, timestamp: ""),
        ]
    )
    .padding()
}
