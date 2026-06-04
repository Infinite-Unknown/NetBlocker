import SwiftUI

@main
struct NetBlockerApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup("NetBlocker") {
            ContentView()
                .environmentObject(model)
                .frame(minWidth: 520, minHeight: 560)
                .onAppear { model.start() }
        }
        .windowResizability(.contentSize)
    }
}
