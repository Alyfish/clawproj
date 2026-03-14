import SwiftUI

/// Final onboarding step showing import summary and transition to the main app.
struct OnboardingCompleteView: View {
    let importCount: Int
    let onFinish: () -> Void

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 64))
                .foregroundStyle(.green)

            Text("You're All Set")
                .font(.title.bold())

            if importCount > 0 {
                Text("\(importCount) password\(importCount == 1 ? "" : "s") imported")
                    .font(.headline)
                    .foregroundStyle(.secondary)
            } else {
                Text("We'll ask for access as you need it.")
                    .font(.headline)
                    .foregroundStyle(.secondary)
            }

            Text("ClawBot can now securely log into sites on your behalf.")
                .font(.subheadline)
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)

            Spacer()

            Button(action: onFinish) {
                Text("Let's go")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(Color.accentColor)
                    .foregroundStyle(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 14))
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 32)
        }
    }
}

#Preview("With imports") {
    OnboardingCompleteView(importCount: 42, onFinish: {})
}

#Preview("No imports") {
    OnboardingCompleteView(importCount: 0, onFinish: {})
}
