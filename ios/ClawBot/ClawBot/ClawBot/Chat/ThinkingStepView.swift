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

// MARK: - Previews

#Preview("Running steps") {
    ThinkingStepsContainer(steps: [
        ThinkingStep(id: "1", description: "Searching flights", status: .running, timestamp: ""),
        ThinkingStep(id: "2", description: "Parsing results", status: .pending, timestamp: ""),
        ThinkingStep(id: "3", description: "Loaded user prefs", status: .done, timestamp: ""),
    ])
    .padding()
}

#Preview("Error state") {
    ThinkingStepsContainer(steps: [
        ThinkingStep(id: "1", description: "API call failed", status: .error, timestamp: ""),
    ])
    .padding()
}

#Preview("Faded out") {
    ThinkingStepsContainer(
        steps: [
            ThinkingStep(id: "1", description: "Done thinking", status: .done, timestamp: ""),
        ],
        isVisible: false
    )
    .padding()
}
