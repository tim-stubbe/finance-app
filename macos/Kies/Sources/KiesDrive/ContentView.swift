import SwiftUI
import MapKit
import KiesCore

struct DriveContentView: View {
    @StateObject private var settings = DriveSettings.shared
    @StateObject private var location = LocationService()
    @StateObject private var planner = RoutePlanner()
    @State private var position: MapCameraPosition = .automatic
    @State private var showSettings = false
    @State private var showJarvis = false
    @State private var selectedStation: FuelStation?

    var body: some View {
        NavigationSplitView {
            routePanel
                .navigationTitle("Kies Drive")
                .toolbar {
                    Button { showJarvis = true } label: { Label("Jarvis", systemImage: "sparkles") }
                    Button { showSettings = true } label: { Label("Einstellungen", systemImage: "gear") }
                }
        } detail: {
            map
        }
        .onAppear {
            location.start()
            if !settings.isReady { showSettings = true }
        }
        .sheet(isPresented: $showSettings) { DriveSettingsView() }
        .sheet(isPresented: $showJarvis) { JarvisDriveView(route: planner.route, destination: planner.destination) }
    }

    private var routePanel: some View {
        List {
            Section("Ziel") {
                TextField("Adresse oder Ort", text: $planner.destinationText)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await planner.searchDestination(near: location.location?.coordinate) } }
                Button("Ziel suchen", systemImage: "magnifyingglass") {
                    Task { await planner.searchDestination(near: location.location?.coordinate) }
                }
                ForEach(planner.suggestions, id: \.self) { item in
                    Button {
                        planner.destination = item
                        planner.destinationText = item.name ?? item.placemark.title ?? "Ziel"
                        planner.suggestions = []
                    } label: {
                        VStack(alignment: .leading) {
                            Text(item.name ?? "Ziel")
                            Text(item.placemark.title ?? "").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                Button("Route berechnen", systemImage: "arrow.triangle.turn.up.right.diamond.fill") {
                    guard let start = location.location?.coordinate else { planner.errorMessage = "Standort ist noch nicht verfügbar."; return }
                    Task {
                        await planner.calculate(from: start, settings: settings)
                        if let route = planner.route { position = .rect(route.polyline.boundingMapRect) }
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(planner.destination == nil || planner.isLoading)
            }

            if let route = planner.route {
                Section("Route") {
                    Label(formatDistance(route.distance), systemImage: "road.lanes")
                    Label(formatTime(route.expectedTravelTime), systemImage: "clock")
                    if settings.avoidTolls { Label("Mautstraßen werden vermieden", systemImage: "eurosign.slash") }
                    Button("Navigation in Apple Karten starten", systemImage: "location.fill") { openInMaps() }
                }
                Section("Fahrhinweise") {
                    ForEach(Array(route.steps.dropFirst().enumerated()), id: \.offset) { _, step in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(step.instructions.isEmpty ? "Weiter" : step.instructions)
                            Text(formatDistance(step.distance)).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }

            Section("Tankstellen auf der Strecke") {
                Picker("Kraftstoff", selection: $settings.fuel) {
                    ForEach(FuelKind.allCases) { Text($0.label).tag($0) }
                }
                .onChange(of: settings.fuel) { _, fuel in Task { await planner.loadStations(fuel: fuel) } }
                if planner.route != nil && planner.stations.isEmpty && !planner.isLoading {
                    Text("Keine geöffneten Tankstellen mit Preis in Routennähe gefunden.").foregroundStyle(.secondary)
                }
                ForEach(planner.stations) { station in
                    Button { selectedStation = station; position = .region(.init(center: station.coordinate, latitudinalMeters: 8_000, longitudinalMeters: 8_000)) } label: {
                        HStack {
                            VStack(alignment: .leading) {
                                Text(station.brand.isEmpty ? station.name : station.brand)
                                Text("\(station.street), \(station.place)").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text(String(format: "%.3f €", station.price)).bold().monospacedDigit()
                        }
                    }
                }
            }
            if let error = planner.errorMessage { Section { Text(error).foregroundStyle(.red) } }
        }
        .overlay { if planner.isLoading { ProgressView("Route und Preise werden geladen …").padding().background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14)) } }
    }

    @ViewBuilder
    private var map: some View {
        switch settings.mapAppearance {
        case .standard: mapBase.mapStyle(.standard(elevation: .realistic))
        case .satellite: mapBase.mapStyle(.imagery(elevation: .realistic))
        case .hybrid: mapBase.mapStyle(.hybrid(elevation: .realistic))
        }
    }

    private var mapBase: some View {
        Map(position: $position) {
            UserAnnotation()
            if let destination = planner.destination { Marker(item: destination) }
            if let route = planner.route { MapPolyline(route.polyline).stroke(.blue, lineWidth: 7) }
            ForEach(planner.stations) { station in
                Annotation(station.brand.isEmpty ? station.name : station.brand, coordinate: station.coordinate) {
                    VStack(spacing: 2) {
                        Image(systemName: "fuelpump.fill").padding(8).background(.green, in: Circle()).foregroundStyle(.white)
                        Text(String(format: "%.3f", station.price)).font(.caption.bold()).padding(.horizontal, 5).background(.regularMaterial, in: Capsule())
                    }
                }
            }
        }
        .mapControls { MapCompass(); MapScaleView(); MapUserLocationButton() }
        .overlay(alignment: .top) {
            HStack {
                if settings.avoidTolls { Label("Vignetten/Maut vermeiden", systemImage: "checkmark.shield.fill") }
                Picker("Karte", selection: $settings.mapAppearance) {
                    ForEach(DriveMapAppearance.allCases) { Text($0.label).tag($0) }
                }
                .pickerStyle(.segmented)
                .frame(maxWidth: 280)
            }
            .padding(9).background(.regularMaterial, in: Capsule()).padding()
        }
    }

    private func openInMaps() {
        guard let destination = planner.destination else { return }
        var options: [String: Any] = [MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeDriving]
        if settings.avoidTolls { options[MKLaunchOptionsDirectionsModeKey] = MKLaunchOptionsDirectionsModeDriving }
        destination.openInMaps(launchOptions: options)
    }
    private func formatDistance(_ metres: Double) -> String { metres >= 1000 ? String(format: "%.1f km", metres / 1000) : "\(Int(metres)) m" }
    private func formatTime(_ seconds: TimeInterval) -> String { let m = Int(seconds / 60); return m >= 60 ? "\(m / 60) Std. \(m % 60) Min." : "\(m) Min." }
}

struct DriveSettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var settings = DriveSettings.shared
    @ObservedObject private var tokens = DeviceTokenStore.shared
    @State private var token = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Kies & Jarvis") {
                    TextField("Server-Adresse", text: $settings.baseURL)
                    SecureField(tokens.token == nil ? "Geräte-Token" : "Neuer Geräte-Token (optional)", text: $token)
                    Button("Token sicher speichern") { if !token.isEmpty { tokens.setToken(token); token = "" } }
                }
                Section("Route") {
                    Toggle("Vignetten und Maut vermeiden", isOn: $settings.avoidTolls)
                    Toggle("Autobahnen vermeiden", isOn: $settings.avoidHighways)
                    Picker("Kraftstoff", selection: $settings.fuel) { ForEach(FuelKind.allCases) { Text($0.label).tag($0) } }
                    Picker("Kartendarstellung", selection: $settings.mapAppearance) { ForEach(DriveMapAppearance.allCases) { Text($0.label).tag($0) } }
                }
                Section { Text("Der Tankpreis-Schlüssel bleibt ausschließlich auf deinem TrueNAS-Server. Der Geräte-Token liegt im Apple-Schlüsselbund.").font(.caption).foregroundStyle(.secondary) }
            }
            .formStyle(.grouped)
            .navigationTitle("Einstellungen")
            .toolbar { Button("Fertig") { dismiss() } }
        }.frame(minWidth: 420, minHeight: 420)
    }
}

struct JarvisDriveView: View {
    let route: MKRoute?
    let destination: MKMapItem?
    @Environment(\.dismiss) private var dismiss
    @State private var message = ""
    @State private var reply = ""
    @State private var loading = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                ScrollView { Text(reply.isEmpty ? "Frag Jarvis nach der Route, einem Zwischenstopp oder deiner Ankunft." : reply).frame(maxWidth: .infinity, alignment: .leading).padding() }
                HStack {
                    TextField("Jarvis fragen …", text: $message).textFieldStyle(.roundedBorder).onSubmit { ask() }
                    Button("Senden", systemImage: "arrow.up.circle.fill") { ask() }.disabled(message.isEmpty || loading)
                }.padding()
            }
            .navigationTitle("Jarvis unterwegs")
            .toolbar { Button("Schließen") { dismiss() } }
        }.frame(minWidth: 440, minHeight: 480)
    }

    private func ask() {
        let routeContext = route.map { " Ziel: \(destination?.name ?? "unbekannt"), Entfernung \(Int($0.distance / 1000)) km, Fahrzeit \(Int($0.expectedTravelTime / 60)) Minuten." } ?? ""
        let prompt = "Du unterstützt mich gerade bei einer Autofahrt.\(routeContext) Meine Frage: \(message)"
        loading = true
        Task { do { reply = try await DriveAPI.askJarvis(prompt) } catch { reply = error.localizedDescription }; loading = false }
    }
}
