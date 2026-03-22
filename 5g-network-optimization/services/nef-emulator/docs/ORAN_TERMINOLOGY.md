# Architecture Terminology Clarification

## O-RAN Compliance Notes

> **Important**: This document clarifies the relationship between this implementation and the O-RAN architecture. Please read before reviewing the codebase.

### Historical Naming vs Functional Reality

The codebase uses "NEF Emulator" for historical reasons (early project scope included 5G Core integration). However, the implemented functionality is **RAN behavior simulation**, not 5G Core NEF.

#### What This Service Actually Implements

| Component | Description |
|-----------|-------------|
| **gNB Signal Propagation** | Path loss models (3GPP TR 38.901) for urban macro/micro cells |
| **Cell Selection & Handover** | A3 event-based handover with hysteresis and TTT |
| **Radio Channel Modeling** | Shadowing (AR1 correlated), fast fading (Rayleigh/Doppler) |
| **UE Mobility Tracking** | Position updates, trajectory history, speed estimation |
| **ML-Based Handover Optimization** | Integration with external ML service for intelligent handover decisions |

#### What This Service Does NOT Implement

- Service-based architecture (SBA) interfaces
- Network exposure to external applications (NEF's actual function)
- QoS flow management at core level
- AMF, SMF, UPF interactions
- N1/N2 interface protocols

### Correct O-RAN Mapping

| Our Component | Functional Role | O-RAN Equivalent | Thesis Terminology |
|---------------|-----------------|------------------|-------------------|
| "NEF Emulator" | RAN Simulator | E2 Node Simulation | **RAN Simulator** or **E2 Node Simulator** |
| ML Service | Decision Engine | Near-RT RIC + xApp | **ML Handover xApp** |
| A3 Rule Engine | Baseline Algorithm | Standard 3GPP Handover | **3GPP A3 Baseline** |
| Network State Manager | State Tracking | E2 Node State | **E2 Node State Manager** |

### Protocol Simplification Scope

**What we simplified:**

1. **Protocol Stack:**
   - Real O-RAN: ASN.1 encoding + SCTP transport + E2AP protocol
   - Our system: JSON encoding + HTTP REST + custom API

2. **Message Format:**
   - Real O-RAN: Binary encoded with strict schema (E2SM)
   - Our system: Human-readable JSON with flexible schema

3. **Subscription Model:**
   - Real O-RAN: Complex subscription management with timers
   - Our system: Simple request-response or WebSocket streaming

4. **Service Models:**
   - Real O-RAN: Formal E2SM definitions (E2SM-KPM, E2SM-RC)
   - Our system: Custom metrics and control messages

**What we preserved:**

1. **Architectural Separation:**
   - RAN logic separate from intelligent controller ✓
   - Clear interface boundary ✓

2. **Functional Capabilities:**
   - Metrics reporting (like E2 Indication) ✓
   - Control actions (like E2 Control) ✓
   - Real-time data streaming ✓

3. **Latency Requirements:**
   - Near-RT decision making (<1 second) ✓

### Justification for Thesis

> "This simplification is appropriate for research focused on ML algorithm performance rather than protocol implementation. The architectural principles and functional outcomes are O-RAN-aligned, even though protocol compliance is not byte-for-byte."

### Recommended Thesis Terminology

When writing your thesis, use the following conventions:

1. **In Introduction:**
   - Acknowledge naming is historical
   - Explain the functional focus on handover optimization

2. **In Architecture Chapter:**
   - Use "RAN Simulator" or "E2 Node Simulator" instead of "NEF"
   - Clearly map to O-RAN reference architecture

3. **In Code References:**
   - Can mention "implemented in the nef-emulator service"
   - But describe function, not name

4. **Be Consistent:**
   - Don't switch between NEF and RAN terminology
   - Pick one and stick with it throughout

### Future Work

For production deployment or journal publication, consider:

1. **Protocol Migration Path:**
   - Implement ASN.1 encoding for E2AP messages
   - Add SCTP transport layer
   - Formal E2SM-RC service model

2. **Near-RT RIC Integration:**
   - Deploy actual O-RAN SC Near-RT RIC
   - Register ML service as proper xApp
   - Implement E2 interface handlers

---

*This clarification document is part of Fix #9 and Fix #10 from the thesis implementation plan.*
