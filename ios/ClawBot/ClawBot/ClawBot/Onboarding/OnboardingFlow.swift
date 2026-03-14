import SwiftUI
import AuthenticationServices

/// 5-step onboarding wizard: Welcome → Enable Extension → CXP Import → Google Sign-In → Complete.
/// Presented on first launch; stores completion flag in UserDefaults.
struct OnboardingFlow: View {
    let onComplete: () -> Void

    @State private var currentStep = 0
    @State private var importCount = 0

    var body: some View {
        TabView(selection: $currentStep) {
            welcomeStep
                .tag(0)

            enableExtensionStep
                .tag(1)

            importOrGoogleStep
                .tag(2)

            googleSignInStep
                .tag(3)

            OnboardingCompleteView(importCount: importCount, onFinish: onComplete)
                .tag(4)
        }
        .tabViewStyle(.page(indexDisplayMode: .never))
        .interactiveDismissDisabled()
        .animation(.easeInOut(duration: 0.3), value: currentStep)
    }

    // MARK: - Step 0: Welcome

    private var welcomeStep: some View {
        VStack(spacing: 24) {
            Spacer()

            Image(systemName: "hand.wave.fill")
                .font(.system(size: 56))
                .foregroundStyle(Color.accentColor)

            Text("Welcome to ClawBot")
                .font(.title.bold())

            Text("Let ClawBot access your accounts seamlessly")
                .font(.headline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)

            Text("We'll help you set up AutoFill and import your passwords so ClawBot can act on your behalf.")
                .font(.subheadline)
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)

            Spacer()

            Button {
                currentStep = 1
            } label: {
                Text("Get Started")
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

    // MARK: - Step 1: Enable Extension

    private var enableExtensionStep: some View {
        VStack(spacing: 24) {
            Spacer()

            Image(systemName: "rectangle.and.pencil.and.ellipsis")
                .font(.system(size: 48))
                .foregroundStyle(Color.accentColor)

            Text("Enable AutoFill")
                .font(.title2.bold())

            Text("Allow ClawBot to fill passwords in apps and Safari.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)

            Spacer()

            VStack(spacing: 12) {
                Button {
                    Task {
                        await enableExtension()
                        advanceFromExtensionStep()
                    }
                } label: {
                    Text("Enable AutoFill")
                        .font(.headline)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.accentColor)
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }

                Button("Skip") {
                    advanceFromExtensionStep()
                }
                .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 32)
        }
    }

    // MARK: - Step 2: Import (iOS 26+) or skip to Google Sign-In

    @ViewBuilder
    private var importOrGoogleStep: some View {
        if #available(iOS 26, *) {
            CXPImportGuideView(
                onDone: { count in
                    importCount = count
                    currentStep = 3
                },
                onSkip: {
                    currentStep = 3
                }
            )
        } else {
            // iOS < 26: no CXP, skip straight to Google Sign-In
            googleSignInStep
        }
    }

    // MARK: - Step 3: Google Sign-In (skippable)

    private var googleSignInStep: some View {
        GoogleSignInStepView(
            onDone: { _ in
                currentStep = 4
            },
            onSkip: {
                currentStep = 4
            }
        )
    }

    // MARK: - Helpers

    private func enableExtension() async {
        if #available(iOS 18, *) {
            await ASSettingsHelper.requestToTurnOnCredentialProviderExtension()
        }
    }

    private func advanceFromExtensionStep() {
        if #available(iOS 26, *) {
            currentStep = 2
        } else {
            // Skip CXP import step on older iOS, go to Google Sign-In
            currentStep = 3
        }
    }
}

#Preview {
    OnboardingFlow(onComplete: {})
}
