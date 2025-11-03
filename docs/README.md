# Documentation Directory

Welcome to the complete documentation for the 5G Network Optimization with ML-based Handover project.

---

## Quick Navigation

### 🚀 **Getting Started**
Start here if you're setting up the project for the first time:

1. **[QUICK_START.md](QUICK_START.md)** - Essential commands and quick reference
2. **[COMPLETE_DEPLOYMENT_GUIDE.md](COMPLETE_DEPLOYMENT_GUIDE.md)** - Comprehensive step-by-step guide
3. **[INDEX.md](INDEX.md)** - Complete documentation index

### 📊 **Thesis & Results**
For generating results and understanding the research:

4. **[THESIS_ABSTRACT.md](THESIS_ABSTRACT.md)** - Project overview and research contributions
5. **[RESULTS_GENERATION_CHECKLIST.md](RESULTS_GENERATION_CHECKLIST.md)** - Step-by-step guide to produce thesis results

### 🏗️ **Architecture & Design**
Deep dives into system architecture:

6. **[architecture/qos.md](architecture/qos.md)** - QoS architecture, flows, and configuration
7. **[qos/synthetic_qos_dataset.md](qos/synthetic_qos_dataset.md)** - Synthetic data generator documentation

---

## Documentation Structure

```
docs/
├── README.md (this file)
├── INDEX.md                              # Master documentation index
├── QUICK_START.md                        # Quick reference guide
├── COMPLETE_DEPLOYMENT_GUIDE.md          # Full deployment instructions
├── THESIS_ABSTRACT.md                    # Research overview
├── RESULTS_GENERATION_CHECKLIST.md       # Thesis results workflow
├── architecture/
│   └── qos.md                            # QoS system architecture
└── qos/
    ├── synthetic_qos_dataset.md          # Dataset generator docs
    └── diagrams/                         # Architecture diagrams
```

---

## Document Purposes

### QUICK_START.md
**Purpose**: Condensed command reference  
**Use When**: You need quick commands without detailed explanations  
**Key Sections**:
- Prerequisites installation
- Starting the system
- Testing ML predictions
- Monitoring commands
- API quick reference

**Estimated Read Time**: 10 minutes  
**Target Audience**: Developers familiar with the system

---

### COMPLETE_DEPLOYMENT_GUIDE.md
**Purpose**: Comprehensive end-to-end guide  
**Use When**: First-time setup or complete system walkthrough  
**Key Sections**:
1. System overview
2. Prerequisites and installation
3. Configuration options
4. Deployment (Docker Compose & Kubernetes)
5. Data generation and collection
6. Model training
7. Testing procedures
8. Monitoring setup
9. Generating thesis results
10. Troubleshooting

**Estimated Read Time**: 60-90 minutes  
**Target Audience**: New users, thesis reviewers, researchers

---

### THESIS_ABSTRACT.md
**Purpose**: Academic overview and research contributions  
**Use When**: Writing thesis, presenting research, or explaining project purpose  
**Key Sections**:
- Problem statement
- Proposed solution
- Technical approach
- Expected results
- Validation strategy
- Implementation highlights
- Contributions to the field

**Estimated Read Time**: 30 minutes  
**Target Audience**: Academic reviewers, researchers, supervisors

---

### RESULTS_GENERATION_CHECKLIST.md
**Purpose**: Systematic workflow for producing thesis results  
**Use When**: Running experiments and generating data for thesis  
**Key Sections**:
- Pre-experiment setup
- Phase 1: Data generation
- Phase 2: ML mode experiment
- Phase 3: A3-only mode experiment
- Phase 4: Visualization generation
- Phase 5: Statistical analysis
- Phase 6: Test execution
- Phase 7: Final deliverables

**Estimated Completion Time**: 3-4 hours  
**Target Audience**: Thesis author, experimenters

---

### architecture/qos.md
**Purpose**: Detailed QoS system architecture  
**Use When**: Understanding QoS flows, configuration, or extending QoS features  
**Key Sections**:
- Flow overview
- Admission control
- Configuration flags
- Failure modes
- Metrics & dashboards
- Feature store integration
- Validation architecture

**Estimated Read Time**: 45 minutes  
**Target Audience**: Developers, system architects

---

### qos/synthetic_qos_dataset.md
**Purpose**: Synthetic data generator documentation  
**Use When**: Generating training data or understanding QoS profiles  
**Key Sections**:
- 3GPP-aligned service profiles (eMBB, URLLC, mMTC)
- Parameter distributions
- CLI usage
- Reproducibility guidance

**Estimated Read Time**: 20 minutes  
**Target Audience**: Data scientists, ML engineers

---

## Suggested Reading Paths

### Path 1: Quick Setup (30 minutes)
For getting the system running ASAP:
1. QUICK_START.md → Prerequisites
2. QUICK_START.md → Start the System
3. QUICK_START.md → Test ML Predictions
4. QUICK_START.md → Monitor Performance

**Goal**: System up and running with basic validation

---

### Path 2: Complete Understanding (2-3 hours)
For comprehensive system knowledge:
1. THESIS_ABSTRACT.md → Understand the research
2. COMPLETE_DEPLOYMENT_GUIDE.md → System Overview
3. COMPLETE_DEPLOYMENT_GUIDE.md → Installation
4. COMPLETE_DEPLOYMENT_GUIDE.md → Configuration
5. architecture/qos.md → QoS deep dive
6. COMPLETE_DEPLOYMENT_GUIDE.md → Deployment Options

**Goal**: Full understanding of system architecture and operation

---

### Path 3: Thesis Results Generation (3-4 hours)
For producing thesis deliverables:
1. RESULTS_GENERATION_CHECKLIST.md → Pre-Experiment Setup
2. RESULTS_GENERATION_CHECKLIST.md → Phase 1-7 (follow sequentially)
3. Verify all checkboxes completed
4. Generate final deliverables package

**Goal**: Complete set of results, visualizations, and metrics for thesis

---

### Path 4: Development & Extension (variable)
For modifying or extending the system:
1. COMPLETE_DEPLOYMENT_GUIDE.md → Prerequisites & Installation
2. architecture/qos.md → Understand QoS architecture
3. Service READMEs:
   - `../5g-network-optimization/services/ml-service/README.md`
   - `../5g-network-optimization/services/nef-emulator/README.md`
4. COMPLETE_DEPLOYMENT_GUIDE.md → Testing
5. Explore codebase with understanding

**Goal**: Ability to modify and extend the system

---

## Key Concepts

### ML vs A3 Handover
- **A3 Rule**: Traditional 3GPP handover based on RSRP thresholds
- **ML Mode**: LightGBM/LSTM-based predictions considering RF metrics, mobility, and QoS
- **Auto Mode**: Automatically enables ML when ≥3 antennas exist

### QoS Service Types
- **URLLC**: Ultra-Reliable Low-Latency (1-10ms, 99.95-99.999% reliability)
- **eMBB**: Enhanced Mobile Broadband (20-80ms, 50-350 Mbps)
- **mMTC**: Massive Machine-Type Communications (100-1000ms, 0.01-1 Mbps)
- **Default**: General-purpose fallback

### System Components
- **NEF Emulator**: 3GPP-compliant Network Exposure Function
- **ML Service**: Machine learning antenna selection service
- **Prometheus**: Metrics collection and storage
- **Grafana**: Visualization and dashboards

---

## External References

### Service Documentation
- [ML Service README](../5g-network-optimization/services/ml-service/README.md)
- [NEF Emulator README](../5g-network-optimization/services/nef-emulator/README.md)
- [Monitoring README](../5g-network-optimization/monitoring/README.md)
- [MLOps README](../mlops/README.md)

### Deployment
- [Kubernetes Guide](../5g-network-optimization/deployment/kubernetes/README.md)
- [Docker Compose Config](../5g-network-optimization/docker-compose.yml)

### Main Project
- [Project README](../README.md)

---

## FAQ

**Q: Which document should I read first?**  
A: If you're new: QUICK_START.md. For comprehensive understanding: COMPLETE_DEPLOYMENT_GUIDE.md.

**Q: How do I generate thesis results?**  
A: Follow RESULTS_GENERATION_CHECKLIST.md step-by-step.

**Q: Where are the API specifications?**  
A: Service READMEs and QUICK_START.md → API Quick Reference.

**Q: How do I understand the QoS system?**  
A: Read architecture/qos.md for complete QoS documentation.

**Q: What if something doesn't work?**  
A: Check COMPLETE_DEPLOYMENT_GUIDE.md → Troubleshooting section.

**Q: Can I deploy to production?**  
A: Yes, see COMPLETE_DEPLOYMENT_GUIDE.md → Kubernetes Deployment.

**Q: How do I extend the ML models?**  
A: Read ML Service README and architecture/qos.md for architecture understanding.

---

## Contributing to Documentation

When updating documentation:

1. **Keep QUICK_START.md concise** - Commands only, minimal explanation
2. **Make COMPLETE_DEPLOYMENT_GUIDE.md comprehensive** - Include all details
3. **Update INDEX.md** when adding new documents
4. **Use consistent formatting** - Follow existing structure
5. **Test all commands** before documenting them
6. **Update cross-references** when moving content

---

## Document Maintenance

| Document | Last Updated | Next Review |
|----------|--------------|-------------|
| QUICK_START.md | Nov 2025 | Before thesis defense |
| COMPLETE_DEPLOYMENT_GUIDE.md | Nov 2025 | Before thesis defense |
| THESIS_ABSTRACT.md | Nov 2025 | Before thesis submission |
| RESULTS_GENERATION_CHECKLIST.md | Nov 2025 | After running experiments |
| architecture/qos.md | Nov 2025 | When QoS features change |

---

## Support

For questions or issues:

1. Check COMPLETE_DEPLOYMENT_GUIDE.md → Troubleshooting
2. Review relevant service README
3. Check GitHub issues (if applicable)
4. Consult thesis supervisor

---

**Documentation Version**: 1.0  
**Generated**: November 2025  
**Maintainer**: Thesis Project Team

