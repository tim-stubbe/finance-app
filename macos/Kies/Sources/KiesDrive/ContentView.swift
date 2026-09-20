import SwiftUI
import MapKit
import Combine
import KiesCore

struct DriveContentView: View {
    @StateObject private var settings = DriveSettings.shared
    @StateObject private var location = LocationService()
    @StateObject private var planner = RoutePlanner.shared
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
        .onReceive(location.$location) { newValue in
            guard let newValue, !planner.legs.isEmpty else { return }
            planner.updateProgress(at: newValue, settings: settings)
        }
        .sheet(isPresented: $showSettings) { DriveSettingsView(planner: planner) }
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

            if !planner.legs.isEmpty {
                Section("Route") {
                    Label(formatDistance(planner.totalDistance), systemImage: "road.lanes")
                    Label(formatTime(planner.totalTravelTime), systemImage: "clock")
                    if settings.avoidTolls { Label("Mautstraßen werden vermieden", systemImage: "eurosign.slash") }
                    if !planner.viaStations.isEmpty {
                        Section {
                            ForEach(planner.viaStations) { via in
                                Label("Zwischenstopp: \(via.brand.isEmpty ? via.name : via.brand)", systemImage: "fuelpump.fill")
                            }
                            Button("Zwischenstopps entfernen", systemImage: "xmark.circle") {
                                guard let start = location.location?.coordinate else { return }
                                Task {
                                    for via in planner.viaStations {
                                        await planner.toggleWaypoint(via, from: start, settings: settings)
                                    }
                                }
                            }
                        }
                    }
                    Button("Navigation in Apple Karten starten", systemImage: "location.fill") { openInMaps() }
                }
                if let plan = planner.longTripPlan {
                    Section("Langstreckenvergleich") {
                        ForEach(plan.results) { result in
                            VStack(alignment: .leading, spacing: 5) {
                                Text("\(result.routeTitle) · \(result.scenario.name)").font(.headline)
                                Text("\(formatDistance(result.distanceMetres)) · \(formatTime(result.totalTime)) inkl. \(result.breaks.count) Pause(n)")
                                Text(String(format: "%.1f l · %.2f € Kraftstoff · %.1f l/100 km", result.fuel.litres, result.fuel.cost, result.fuel.averageConsumptionLPer100km))
                                switch result.toll {
                                case .known(let amount, let currency, let source):
                                    Text("Maut: \(NSDecimalNumber(decimal: amount).stringValue) \(currency) · \(source)")
                                case .noToll(let source):
                                    Text("Keine Maut · \(source)")
                                case .unknown(let reason):
                                    Text("Mautkosten unbekannt · \(reason)").foregroundStyle(.secondary)
                                }
                                ForEach(result.breaks) { stop in
                                    Label(stop.candidate?.name ?? "Pausenort entlang der Route suchen", systemImage: "cup.and.saucer.fill")
                                    Text(stop.explanation).font(.caption).foregroundStyle(.secondary)
                                    if stop.candidate != nil {
                                        Button("Als Zwischenstopp übernehmen") {
                                            guard let start = location.location?.coordinate else { return }
                                            Task { await planner.addPlannedBreak(stop, from: start, settings: settings) }
                                        }
                                        .buttonStyle(.bordered)
                                    }
                                }
                            }
                        }
                        comparisonSummary(plan)
                        Text(plan.note).font(.caption).foregroundStyle(.secondary)
                    }
                }
                Section("Fahrhinweise") {
                    ForEach(Array(planner.legs.enumerated()), id: \.offset) { legIndex, leg in
                        ForEach(Array(leg.steps.dropFirst().enumerated()), id: \.offset) { _, step in
                            VStack(alignment: .leading, spacing: 3) {
                                Text(step.instructions.isEmpty ? "Weiter" : step.instructions)
                                Text(formatDistance(step.distance)).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        if legIndex == 0 && planner.legs.count > 1 {
                            Label("Zwischenstopp erreicht", systemImage: "fuelpump.fill").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }

            Section("Tankstellen auf der Strecke") {
                Picker("Kraftstoff", selection: $settings.fuel) {
                    ForEach(FuelKind.allCases) { Text($0.label).tag($0) }
                }
                .onChange(of: settings.fuel) { _, fuel in Task { await planner.loadStations(fuel: fuel) } }
                if settings.fuel == .superplus {
                    Text("* Keine eigene SuperPlus-Preisquelle verfügbar - angezeigt wird der Super-(E5)-Preis als Näherung.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                if planner.route != nil && planner.stations.isEmpty && !planner.isLoading {
                    Text("Keine geöffneten Tankstellen mit Preis in Routennähe gefunden.").foregroundStyle(.secondary)
                }
                ForEach(planner.stations) { station in
                    let isVia = planner.viaStations.contains(where: { $0.id == station.id })
                    HStack {
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
                        .buttonStyle(.plain)
                        Button {
                            guard let start = location.location?.coordinate else { return }
                            Task { await planner.toggleWaypoint(station, from: start, settings: settings) }
                        } label: {
                            Image(systemName: isVia ? "checkmark.circle.fill" : "plus.circle")
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(isVia ? .green : .accentColor)
                        .disabled(planner.route == nil)
                        .help(isVia ? "Als Zwischenstopp entfernen" : "Als Zwischenstopp zur Route hinzufügen")
                    }
                }
            }
            if let error = planner.errorMessage {
                Section {
                    Text(error).foregroundStyle(.red)
                    if let offline = planner.offlineRoute {
                        offlineRouteView(offline)
                    }
                }
            }
        }
        .overlay { if planner.isLoading || planner.isRecalculating { ProgressView(planner.isRecalculating ? "Route wird neu berechnet …" : "Route und Preise werden geladen …").padding().background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14)) } }
    }

    @ViewBuilder
    private var map: some View {
        switch settings.mapAppearance {
        case .standard: mapBase.mapStyle(.standard(elevation: .realistic, showsTraffic: true))
        case .satellite: mapBase.mapStyle(.imagery(elevation: .realistic))
        case .hybrid: mapBase.mapStyle(.hybrid(elevation: .realistic, showsTraffic: true))
        }
    }

    private var mapBase: some View {
        Map(position: $position) {
            UserAnnotation()
            if let destination = planner.destination { Marker(item: destination) }
            ForEach(Array(planner.legs.enumerated()), id: \.offset) { _, leg in
                MapPolyline(leg.polyline).stroke(.blue, lineWidth: 7)
            }
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
        .overlay(alignment: .topLeading) {
            if let coordinate = location.location?.coordinate,
               let limit = planner.currentSpeedLimit(near: coordinate) {
                speedLimitSign(limit).padding()
            }
        }
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
        .overlay(alignment: .bottom) {
            VStack(spacing: 8) {
                if planner.speedWarning {
                    Label("Zu schnell - Tempolimit beachten", systemImage: "exclamationmark.triangle.fill")
                        .padding(9).background(.red, in: Capsule()).foregroundStyle(.white)
                }
                if let announcement = planner.lastAnnouncement {
                    Label(announcement, systemImage: "speaker.wave.2.fill")
                        .padding(9).background(.regularMaterial, in: Capsule())
                }
            }
            .padding()
        }
    }

    /// Zeigt die zuletzt zwischengespeicherte Route (Ziel, Fahrhinweise,
    /// Tankstellen) an, damit unterwegs auch ohne Verbindung noch eine
    /// Orientierung möglich ist - ohne Kartenmaterial, nur als Textliste.
    @ViewBuilder
    private func offlineRouteView(_ cached: CachedRoute) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Label("Zwischengespeicherte Route (offline)", systemImage: "icloud.slash")
                .font(.headline)
            Text("Ziel: \(cached.destinationName)")
            ForEach(Array(cached.legs.enumerated()), id: \.offset) { _, leg in
                Label("\(formatDistance(leg.distance)) · \(formatTime(leg.travelTime))", systemImage: "road.lanes")
                ForEach(Array(leg.steps.enumerated()), id: \.offset) { _, step in
                    Text(step.instructions.isEmpty ? "Weiter" : step.instructions)
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            if !cached.stations.isEmpty {
                Text("Tankstellen (zuletzt bekannt):").font(.caption).bold()
                ForEach(cached.stations) { station in
                    Text("\(station.brand.isEmpty ? station.name : station.brand): \(String(format: "%.3f €", station.price))")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            Text("Stand: \(cached.savedAt.formatted(date: .abbreviated, time: .shortened))")
                .font(.caption2).foregroundStyle(.secondary)
        }
    }

    /// Rundes, deutsches Tempolimit-Schild - weißer Grund mit rotem Ring,
    /// bei "kein Limit" (freie Autobahn) ein durchgestrichenes Schild.
    @ViewBuilder
    private func speedLimitSign(_ limit: SpeedLimitResult) -> some View {
        ZStack {
            Circle().fill(.white).frame(width: 56, height: 56)
            if limit.unlimited {
                Circle().strokeBorder(.black, lineWidth: 3)
                Text("120").font(.system(size: 16, weight: .bold)).foregroundStyle(.black)
                Rectangle().fill(.black).frame(width: 56, height: 4).rotationEffect(.degrees(-35))
            } else if let maxspeed = limit.maxspeed {
                Circle().strokeBorder(.red, lineWidth: 5)
                Text("\(maxspeed)").font(.system(size: 20, weight: .bold)).foregroundStyle(.black)
            }
        }
        .shadow(radius: 3)
    }

    private func openInMaps() {
        guard let destination = planner.destination else { return }
        var options: [String: Any] = [MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeDriving]
        if settings.avoidTolls { options[MKLaunchOptionsDirectionsModeKey] = MKLaunchOptionsDirectionsModeDriving }
        destination.openInMaps(launchOptions: options)
    }
    private func formatDistance(_ metres: Double) -> String { metres >= 1000 ? String(format: "%.1f km", metres / 1000) : "\(Int(metres)) m" }
    private func formatTime(_ seconds: TimeInterval) -> String { let m = Int(seconds / 60); return m >= 60 ? "\(m / 60) Std. \(m % 60) Min." : "\(m) Min." }

    @ViewBuilder
    private func comparisonSummary(_ plan: LongTripPlan) -> some View {
        let configured = plan.results.first { $0.scenario.targetSpeedKmh == settings.targetSpeedKmh }
        let fast = configured.flatMap { base in
            plan.results.first { $0.routeTitle == base.routeTitle && $0.scenario.targetSpeedKmh == 200 }
        }
        if let configured, let fast, configured.id != fast.id {
            let delta = RouteComparisonDelta(from: configured, to: fast)
            VStack(alignment: .leading, spacing: 4) {
                Text("200 statt \(Int(settings.targetSpeedKmh)) km/h").font(.headline)
                Text("\(signedTime(delta.timeDifference)) · \(signed(delta.fuelDifferenceLitres, unit: "l")) · \(signed(delta.fuelCostDifference, unit: "€"))")
                Text("Nur für als unbegrenzt erkannte, geeignete Abschnitte gerechnet.").font(.caption).foregroundStyle(.secondary)
            }
        }

        let selectedSpeed = settings.targetSpeedKmh
        let routeOptions = plan.results.filter { $0.scenario.targetSpeedKmh == selectedSpeed }
        if routeOptions.count >= 2 {
            let delta = RouteComparisonDelta(from: routeOptions[0], to: routeOptions[1])
            VStack(alignment: .leading, spacing: 4) {
                Text("Mautroute gegenüber Alternative").font(.headline)
                Text("\(signedTime(delta.timeDifference)) · \(signed(delta.distanceDifferenceMetres / 1_000, unit: "km")) · \(signed(delta.fuelCostDifference, unit: "€ Kraftstoff"))")
                if let savings = delta.tollSavings {
                    Text("Mautersparnis: \(NSDecimalNumber(decimal: savings).doubleValue, format: .currency(code: "EUR"))")
                } else {
                    Text("Mautersparnis nicht berechenbar: keine verifizierten Preise.").font(.caption).foregroundStyle(.secondary)
                }
            }
        }
    }

    private func signed(_ value: Double, unit: String) -> String {
        String(format: "%@%.1f %@", value > 0 ? "+" : "", value, unit)
    }

    private func signedTime(_ seconds: TimeInterval) -> String {
        let minutes = Int((seconds / 60).rounded())
        return "\(minutes > 0 ? "+" : "")\(minutes) Min."
    }
}

struct DriveSettingsView: View {
    @ObservedObject var planner: RoutePlanner
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
                    Toggle("Sprachansagen", isOn: $settings.voiceGuidance)
                    Picker("Kraftstoff", selection: $settings.fuel) { ForEach(FuelKind.allCases) { Text($0.label).tag($0) } }
                    Picker("Kartendarstellung", selection: $settings.mapAppearance) { ForEach(DriveMapAppearance.allCases) { Text($0.label).tag($0) } }
                }
                Section("Langstrecke & Fahrzeug") {
                    Stepper("Zieltempo auf geeigneten freien Abschnitten: \(Int(settings.targetSpeedKmh)) km/h", value: $settings.targetSpeedKmh, in: 100...220, step: 10)
                    LabeledContent("Normverbrauch") {
                        TextField("l/100 km", value: $settings.consumptionLPer100km, format: .number.precision(.fractionLength(1)))
                            .multilineTextAlignment(.trailing).frame(width: 90)
                    }
                    LabeledContent("Tankgröße") {
                        TextField("Liter", value: $settings.tankCapacityL, format: .number.precision(.fractionLength(0)))
                            .multilineTextAlignment(.trailing).frame(width: 90)
                    }
                    LabeledContent("Kraftstoffpreis") {
                        TextField("€/l", value: $settings.fuelPricePerLitre, format: .number.precision(.fractionLength(2)))
                            .multilineTextAlignment(.trailing).frame(width: 90)
                    }
                    Text("Das Zieltempo wird nur auf Streckenanteile ohne bekanntes Limit angewendet. MapKit-Verkehr, begrenzte Abschnitte und Pausen bleiben berücksichtigt.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section("Offline-Zwischenspeicher") {
                    Button("Zwischengespeicherte Route löschen", role: .destructive) { planner.clearOfflineCache() }
                        .disabled(planner.offlineRoute == nil)
                }
                Section("Über") {
                    LabeledContent("App-Version", value: DriveSettings.appVersionString)
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
