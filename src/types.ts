export interface Asset { path: string; name: string; downloadName?: string; bytes: number; sha256: string; encoding?: 'gzip' | 'zip-entry'; transferBytes?: number; transferSha256?: string }
export interface Stock { id: string; name: string; type: string; stage: string; brand: string; use: string; recommendedPrint: string | null; sha256: string }
export interface Sample {
  id: string; name: string; category: string; credit: string; source: string | null; path: string; width: number; height: number;
  inputKind: 'camera-std' | 'synthetic-srgb' | 'uploaded-srgb' | 'review-jpeg'; sourceFilename?: string; previewLut: 'std';
  nameEn?: string; categoryEn?: string; thumbnailPath?: string; cameraId?: string; cameraName?: string; scenes?: string[];
  notes?: string; notesEn?: string; stdEvidence?: string; stdEvidenceEn?: string; preproduction?: boolean;
  originalUrl?: string; sourceSha256?: string; preparedSha256?: string; cameraMetadata?: Record<string, unknown>;
}
export interface ExternalSamples {
  schemaVersion: 1; localOnly: true; samples: Sample[];
  models: { id: string; name: string }[];
  scenes: { id: string; name: string; nameEn: string }[];
  missing: { camera: string; scene: string; reason: string; reasonEn: string }[];
}
export interface Metric { mean: number; p95: number; p99: number; max: number; samples: number }
export type NegativeProcessMode = 'negative_print' | 'negative_digital' | 'reference_interpretation'
export type OfficialProcessMode = 'official_direct' | 'official_print'
export type ProcessPreference = NegativeProcessMode | OfficialProcessMode
export type ProcessMode = ProcessPreference | 'positive_direct' | 'supplied_direct'
export type LutFiles = Record<'vlog' | 'std' | 'zip' | 'qa' | 'provenance', Asset>
export interface FilmReference { title: string; url: string; author?: string; evidence?: string; camera?: string; exposure?: string; development?: string; scanner?: string; post?: string; role?: string; observation?: string }
export interface ReferenceLook { film: string; name: string; description: string; adjustments?: string[]; references: FilmReference[] }
export interface ReferenceStudy { methodId: string; looks: ReferenceLook[]; limitation?: string }
export interface FujiLook { film: string; name: string; sourceFile: string; sourceSha256: string }
export interface FujiStudy { methodId: string; model: string; packageVersion: string; sourceUrl: string; downloadUrl: string; sourceSha256: string; looks: FujiLook[]; limitation?: string }
export interface FilmCast {
  method: 'spektrafilm-print-reference-blend-v1'; amountPolicy: 'chroma-target'; amount: number; percent: number; targetChroma: number; experimental: true;
  referenceFilm: string; filmCC: number[]; referenceCC: number[]; appliedCC: number[];
  grayChroma: number; grayHue: number
  /** Editorial-hue films: own filters (amount 1) plus a solved M/Y shift towards targetHue. */
  directionPolicy?: 'editorial-hue'; targetHue?: number; hueShiftCC?: number[]
}
export interface Combination {
  id: string; film: string; paper: string | null; number: number;
  /** Experimental film-cast variant: the base negative print it belongs to. */
  castBaseId?: string; filmCast?: FilmCast;
  processMode: ProcessMode;
  status: 'ready' | 'failed' | 'unsupported' | 'not-generated'; reason?: string;
  seconds?: number; files?: LutFiles;
  stdMethod?: 'camera-vlog-alchemy-v1' | 'supplied-fuji-std-v1';
  suppliedStd?: { cameraId: string; asset: Asset };
  stdByCamera?: Record<string, { std: Asset; zip: Asset; qa: { tetrahedral: Metric; trilinear: Metric }; warnings: string[] }>;
  previews?: Record<string, Asset>;
  previewMode?: 'runtime-std';
  qa?: { singleTonePrecurve?: { method: string }; fileChecks: string; cameraVerified: boolean; warnings: string[]; vlogVsDirectEngine: { tetrahedral: Metric }; stdVsDirectEngine?: { tetrahedral: Metric }; stdVsContinuousComposition?: { tetrahedral: Metric } }
}
export interface CameraAdapter {
  id: string; name: string; asset: Asset; validation: 'controlled' | 'field' | 'pending'; cameraUse: 'in-camera' | 'post-only'
}
export interface SuppliedFujiLook { stock: Stock; std: Asset; sourceFile: string; sourceSha256: string }
export interface SuppliedFuji { methodId: 'supplied-fuji-std-v1'; cameraId: string; looks: SuppliedFujiLook[]; provenance: Asset; notice: Asset }
export interface Catalog {
  schemaVersion: number; engineCommit: string; engineVersion: string; adapter: string;
  films: Stock[]; papers: Stock[]; samples: Sample[]; combinations: Combination[];
  counts: Record<string, number>; output: string; resolution: number
  cameraAdapters?: { method: 'camera-vlog-alchemy-v1'; defaultCamera: string; sourceUrl: string; commit: string; models: CameraAdapter[] }
  referenceStudy?: ReferenceStudy
  fujiStudy?: FujiStudy
  suppliedFuji?: SuppliedFuji
  filmCast?: { method: 'spektrafilm-print-reference-blend-v1'; amountPolicy: 'chroma-target'; minAmount: number; targetChroma: Record<string, number>; targetHue?: Record<string, number>; referenceFilm: string; variants: number; skipped: { id: string; reason: string }[]; limitations: string[] }
  printTiming?: {
    method: 'spektrafilm-print-filter-timing-v1'; experimental: true; unit: 'Kodak CC'; channels: ['M', 'Y']
    gridCC: number[]; rangeCC: [number, number]; resolution: number; limitations: string[]
    packs: Record<string, { asset: Asset; wire: { min: number; max: number }; qa: Record<string, { mean: number; p99: number; max: number }> }>
  }
  sourceCode?: { path: string; bytes: number; sha256: string }
}
