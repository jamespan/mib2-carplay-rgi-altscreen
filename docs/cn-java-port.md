# CN P1002 Java build profile

This profile ports the fork's RGI/AltScreen Java implementation to the actual
`MHI2Q_CN_AUG22_P1002` API. It does not carry forward the old road-bar capability
trial or its context manager. The upstream `java_patch/` sources remain unchanged;
four ABI-specific copies are generated under `build/java-profile/`.

## Inputs and repeatable build

Use a complete converted JAR from **the target unit's** `lsd.jxe`, including the
original JCL and OSGi classes. Do not substitute the European/US JAR or the small
analysis/stub JARs used by older experiments. Do not deploy or commit stock inputs.
The local CN conversion contains 30,348 classes and no skipped classes. It was
produced with `luka-dev/jxe2jar` commit
`0399e20e6568f45694b233070a015444b1998f98`, using `--dont-infer-enclosing`, without
AccessInline/decompiler-only accessor rewriting. Original JXE SHA-256:
`ce6f1a47d000bc5439124ca5d4439caccc3612ee7ca3ac3cca1632be9b8ea408`.

```sh
STOCK_JAR=/private/inputs/CN_P1002-combined.jar \
STOCK_JCL=same \
STOCK_FIRMWARE=MHI2Q_CN_AUG22_P1002 \
CARPLAY_BUILD_ID=cn-p1002-rgi-v1 \
bash scripts/build_java.sh

python3 tools/audit_cn_java.py --stock /private/inputs/CN_P1002-combined.jar
```

The default JDK 8 container has no network access during compilation. Set
`JAVA_BUILD_IMAGE` to an immutable image digest for a pinned build; the first
local build used `eclipse-temurin:8-jdk-jammy` digest
`sha256:5c25ccda5b0154fca89cbbca34afab0e0a198aa23e7f23b1169dee5577e33e03`
(`javac 1.8.0_504`). Alternatively use `JAVA_BUILD_MODE=local` and a JDK 8
`JAVA_HOME`. The auditor supports JDK 8 and 11 without an external ASM JAR.
`STOCK_JAR_SHA256` can pin the exact local conversion. ZIP timestamps mean a fresh
build may produce a different JAR hash: always rerun the auditor after rebuilding.

Build records:

- `build/java-inputs.json`: stock/JCL hash, firmware and build ID; hashes of every
  Java source/resource and the build/profile-generation tools, captured before compilation.
- `build/java-profile/adaptations.json`: counted substitutions and source hashes;
  adjacent `.diff` files show the generated CN differences.
- `build/java-build.json`: actual payload hash, class inventory and major version;
  source hashes rechecked after compilation. Staging checks these again, including
  `SKIP_BUILD=1`, so edited sources cannot silently ship with an older binary.
- `build/cn-java-audit.json`: exact payload/stock hash, PASS/FAIL, link counts,
  individual host test results and explicit `vehicle_validated: false`.
- `build/cn-java-audit/*.log`: complete compiler/linkage/test evidence.

## Four confirmed ABI differences

The unmodified fork fails against the real CN stock with 38 compiler errors.
These are firmware API differences, not missing third-party dependencies.
`tools/prepare_cn_java.py` checks every source replacement count and fails if the
upstream source no longer matches.

| Area | CN stock evidence | CN generated adaptation |
|---|---|---|
| `ExternalEventsListener` | Three-argument constructor `(IContext, IStateHandler, IDispatcher)`, no `ISmartphoneProperties` field or HFP-property update in the original callback | Restore the CN constructor and omit the newer property call; retain `PhoneStateUpdate`, upstream lifecycle/debounce and PDC guard |
| `HighPriorityResourceTracker` | Seven-argument constructor ending in `PropertyFactory`; no MURVC property or `EmergencyNumber` class | Restore that constructor and remove only nonexistent property writes/type-dependent diagnostic method; retain RVC/eCall state, resource handling and upstream OPS guard |
| `CarplayDSILifecycleController` | `IDSIResource` getters take no boolean; original private `convertResource2DSIResourceRequest` passes priority `initial ? 2 : 1` | Use the CN getter signatures and original priority rule; retain upstream input, navignore and lifecycle changes |
| `PartialPopupManagerEvoHigh` | Original superclass is `de.esolutions.hmi.widgets.audi.base.PartialPopupManager`, with the same three-argument super-constructor | Use that original CN superclass while retaining the fork's popup/OPS behavior |

The original CN resource method was checked in `javap -c -p`: the take-type
getter appears at bytecode offset 37, priority selection at 116–125, and the three
parameterless constraint getters follow it. No guessed replacement class or US
implementation was added to satisfy an absent CN API.

## Validation completed locally

- The full fork compiles against the original CN JCL/OSGi, output Java 1.4 class
  major 48: 124 patch classes, with no copied `java.*`, `javax.*`, `org.osgi.*` or
  IBM runtime classes in the output.
- Bidirectional member linkage: 9,637 patch references plus 3,877 references from
  30,306 remaining original CN classes; **zero missing/static/access errors**.
  The audit ran successfully using both JDK 8 and JDK 11's analysis ASM.
- 18 upstream host suites pass against the real CN classpath: route deltas,
  road/ETA presentation, text scrolling, distance/bargraph, maneuver parity,
  renderer viewport, Classic/Sport layer visibility and context choice, route
  end/restart, stale callbacks, lane lifecycle and RGI delivery recovery.
- `CnResourceRequestTest` executes the actual compiled private conversion path:
  initial/update priority, both ownership directions and empty input all pass.

Five source-provenance regression tests also pass, including changed/added/deleted
inputs and missing or corrupt manifests.

This does **not** prove every replaced OEM method is behaviorally identical to
CN stock. Some host probes disable HotSpot verification for reconstructed J9
stock bytecode, as upstream already does; the production patch is unchanged.
Real J9 loading, CarPlay connect/disconnect, AMap RGD metadata, Classic/Sport
transitions, reverse-camera/OPS, phone/audio interruption and native-map recovery
still require vehicle testing. Compilation and linkage must not be described as
successful installation or proof of those runtime behaviors.
