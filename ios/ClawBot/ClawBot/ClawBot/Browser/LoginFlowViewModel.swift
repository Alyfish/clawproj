import Foundation
import Combine
import SwiftUI
import UIKit

// MARK: - LoginElement

struct LoginElement: Identifiable {
    let id: Int  // ref number from snapshot
    let tag: String
    let type: String?
    let text: String
    let rect: CGRect  // position on the page (in page coordinates)
}

// MARK: - LoginFlowViewModel

@MainActor
final class LoginFlowViewModel: ObservableObject {

    // MARK: Published state

    @Published var currentImage: UIImage?
    @Published var elements: [LoginElement] = []
    @Published var currentURL: String = ""
    @Published var pageTitle: String = ""
    @Published var profile: String = ""
    @Published var isActive: Bool = false
    @Published var inputText: String = ""
    @Published var selectedRef: Int? = nil
    @Published var statusMessage: String = ""

    // MARK: Dependencies

    private let webSocket: any WebSocketServiceProtocol

    // MARK: Init

    init(webSocket: any WebSocketServiceProtocol) {
        self.webSocket = webSocket
    }

    // MARK: Frame handling

    func handleFrame(
        imageBase64: String,
        url: String,
        profile: String,
        pageTitle: String,
        elements: [[String: AnyCodable]]
    ) {
        // Decode base64 JPEG → UIImage
        if let data = Data(base64Encoded: imageBase64) {
            currentImage = UIImage(data: data)
        }

        self.currentURL = url
        self.profile = profile
        self.pageTitle = pageTitle

        // Parse element dicts into LoginElement structs
        self.elements = elements.compactMap { dict -> LoginElement? in
            guard
                let ref = (dict["ref"]?.value as? NSNumber)?.intValue,
                let tag = dict["tag"]?.stringValue
            else { return nil }

            let type = dict["type"]?.stringValue
            let text = dict["text"]?.stringValue ?? ""

            // Parse rect
            var rect = CGRect.zero
            if let rectDict = dict["rect"]?.value as? [String: Any] {
                let x = (rectDict["x"] as? NSNumber)?.doubleValue ?? 0
                let y = (rectDict["y"] as? NSNumber)?.doubleValue ?? 0
                let w = (rectDict["w"] as? NSNumber)?.doubleValue ?? 0
                let h = (rectDict["h"] as? NSNumber)?.doubleValue ?? 0
                rect = CGRect(x: x, y: y, width: w, height: h)
            }

            return LoginElement(id: ref, tag: tag, type: type, text: text, rect: rect)
        }

        // Extract domain for status
        if let urlObj = URL(string: url) {
            statusMessage = "Logging into \(urlObj.host ?? url) — profile: \(profile)"
        }

        if !isActive {
            isActive = true
        }
    }

    // MARK: User actions

    func sendInput(ref: Int, text: String) {
        webSocket.sendLoginInput(profile: profile, ref: ref, text: text)
        inputText = ""
        selectedRef = nil
    }

    func sendClick(ref: Int) {
        webSocket.sendLoginClick(profile: profile, ref: ref)
    }

    func done() {
        webSocket.sendLoginDone(profile: profile)
        isActive = false
    }
}
