import SwiftUI

struct ApprovalDetailView: View {
    let request: ApprovalRequest
    var onApprove: ((String) -> Void)?
    var onDeny: ((String) -> Void)?

    @Environment(\.dismiss) private var dismiss

    @State private var showDestructiveConfirmation = false
    @State private var actionState: ActionState = .idle

    enum ActionState: Equatable {
        case idle
        case approving
        case denying
        case success(approved: Bool)
        case error(String)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("ClawBot needs your permission before taking this action on your behalf.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)

                headerSection
                descriptionSection
                detailsSection
                taskLinkSection
                actionButtons
            }
            .padding()
        }
        .navigationTitle("Review Action")
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog(
            "Confirm \(request.action.displayName)",
            isPresented: $showDestructiveConfirmation,
            titleVisibility: .visible
        ) {
            Button("Yes, \(request.action.displayName)", role: .destructive) {
                performApprove()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This action cannot be undone. Are you sure you want to proceed?")
        }
    }

    // MARK: - Header

    private var headerSection: some View {
        HStack(spacing: 14) {
            // Large action icon
            Image(systemName: request.action.iconName)
                .font(.title)
                .foregroundStyle(actionColor)
                .frame(width: 56, height: 56)
                .background(actionColor.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 14))

            VStack(alignment: .leading, spacing: 4) {
                Text(request.action.displayName)
                    .font(.title3)
                    .fontWeight(.semibold)

                Text(request.timeAgo)
                    .font(.caption)
                    .foregroundStyle(.tertiary)

                if request.action.isDestructive {
                    HStack(spacing: 4) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .font(.caption2)
                        Text("Destructive action")
                            .font(.caption2)
                            .fontWeight(.medium)
                    }
                    .foregroundStyle(.red)
                }
            }
        }
    }

    // MARK: - Description

    private var descriptionSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Description")
                .font(.headline)

            Text(request.description)
                .font(.body)
                .foregroundStyle(.secondary)
                .padding()
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color(.systemGray6))
                .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    // MARK: - Details (key-value pairs)

    private var detailsSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Details")
                .font(.headline)

            VStack(spacing: 0) {
                ForEach(sortedDetails, id: \.key) { key, value in
                    HStack {
                        Text(key)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .frame(width: 100, alignment: .leading)

                        Text(value)
                            .font(.subheadline)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)

                    if key != sortedDetails.last?.key {
                        Divider()
                            .padding(.leading, 14)
                    }
                }
            }
            .background(Color(.systemGray6))
            .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }

    private var sortedDetails: [(key: String, value: String)] {
        request.details.sorted { $0.key < $1.key }.map { (key: $0.key, value: $0.value) }
    }

    // MARK: - Task Link

    private var taskLinkSection: some View {
        HStack(spacing: 8) {
            Image(systemName: "link")
                .font(.caption)
                .foregroundStyle(.blue)
            Text("Task: \(request.taskId)")
                .font(.caption)
                .foregroundStyle(.blue)
        }
    }

    // MARK: - Action Buttons

    @ViewBuilder
    private var actionButtons: some View {
        switch actionState {
        case .idle:
            idleButtons
        case .approving:
            ProgressView("Approving...")
                .frame(maxWidth: .infinity)
                .padding()
        case .denying:
            ProgressView("Denying...")
                .frame(maxWidth: .infinity)
                .padding()
        case .success(let approved):
            successView(approved: approved)
        case .error(let message):
            errorView(message: message)
        }
    }

    private var idleButtons: some View {
        VStack(spacing: 12) {
            // Approve button
            Button(action: handleApprove) {
                HStack {
                    Image(systemName: "checkmark.circle.fill")
                    Text("Approve")
                }
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(.green)
                .foregroundStyle(.white)
                .clipShape(RoundedRectangle(cornerRadius: 14))
            }

            // Deny button
            Button(action: handleDeny) {
                HStack {
                    Image(systemName: "xmark.circle.fill")
                    Text("Deny")
                }
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(.red.opacity(0.12))
                .foregroundStyle(.red)
                .clipShape(RoundedRectangle(cornerRadius: 14))
            }
        }
        .padding(.top, 8)
    }

    private func successView(approved: Bool) -> some View {
        VStack(spacing: 8) {
            Image(systemName: approved ? "checkmark.circle.fill" : "xmark.circle.fill")
                .font(.largeTitle)
                .foregroundStyle(approved ? .green : .red)
            Text(approved ? "Approved" : "Denied")
                .font(.headline)
                .foregroundStyle(approved ? .green : .red)
        }
        .frame(maxWidth: .infinity)
        .padding()
        .onAppear {
            // Auto-dismiss after brief display
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
                dismiss()
            }
        }
    }

    private func errorView(message: String) -> some View {
        VStack(spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.title)
                .foregroundStyle(.orange)
            Text(message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)

            Button("Try Again") {
                actionState = .idle
            }
            .font(.subheadline)
            .fontWeight(.medium)
        }
        .frame(maxWidth: .infinity)
        .padding()
    }

    // MARK: - Actions

    private func handleApprove() {
        if request.action.isDestructive {
            showDestructiveConfirmation = true
        } else {
            performApprove()
        }
    }

    private func performApprove() {
        actionState = .approving
        onApprove?(request.id)
        // Simulate brief delay then show success
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            actionState = .success(approved: true)
        }
    }

    private func handleDeny() {
        actionState = .denying
        onDeny?(request.id)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            actionState = .success(approved: false)
        }
    }

    // MARK: - Helpers

    private var actionColor: Color {
        switch request.action.iconColor {
        case "blue": .blue
        case "green": .green
        case "purple": .purple
        case "red": .red
        case "orange": .orange
        case "indigo": .indigo
        default: .gray
        }
    }
}

// MARK: - Previews

#Preview("Payment — destructive") {
    NavigationStack {
        ApprovalDetailView(
            request: .mockPay,
            onApprove: { id in print("Approved \(id)") },
            onDeny: { id in print("Denied \(id)") }
        )
    }
}

#Preview("Delete — destructive") {
    NavigationStack {
        ApprovalDetailView(request: .mockDelete)
    }
}

#Preview("Send — non-destructive") {
    NavigationStack {
        ApprovalDetailView(request: .mockSend)
    }
}

#Preview("Share personal info") {
    NavigationStack {
        ApprovalDetailView(request: .mockSharePersonalInfo)
    }
}

#Preview("Submit") {
    NavigationStack {
        ApprovalDetailView(request: .mockSubmit)
    }
}
