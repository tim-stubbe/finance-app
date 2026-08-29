import Foundation

/// Gemeinsame URLSession fuer alle Aufrufe an den eigenen Kies-Server.
///
/// Der TrueNAS-Server terminiert TLS mit einem selbstsignierten Zertifikat
/// (nur ueber Tailscale erreichbar, kein oeffentlich vertrauenswuerdiges
/// Zertifikat noetig - analog zu den `curl -k`-Aufrufen im Deployment). Ein
/// permissiver Delegate akzeptiert dieses Zertifikat; `URLSession.shared`
/// wuerde es ablehnen ("Das Zertifikat fuer diesen Server ist ungueltig").
///
/// EINE zentrale Stelle statt pro Feature (Entity-Sync, Apple Health, Siri-
/// Intent) eine eigene Kopie des Delegates - sonst faellt genau eine davon
/// beim naechsten Umbau durchs Raster.
public enum KiesHTTP {
    public static let session: URLSession = URLSession(
        configuration: .default, delegate: _TrustingDelegate(), delegateQueue: nil
    )

    private final class _TrustingDelegate: NSObject, URLSessionDelegate {
        func urlSession(
            _ session: URLSession, didReceive challenge: URLAuthenticationChallenge,
            completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void
        ) {
            if let trust = challenge.protectionSpace.serverTrust {
                completionHandler(.useCredential, URLCredential(trust: trust))
            } else {
                completionHandler(.performDefaultHandling, nil)
            }
        }
    }
}
