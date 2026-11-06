import type { StudyAnalysisResponse } from "@radar-ai/contracts";

export interface DemoStudyEntry {
  analysis: StudyAnalysisResponse;
  code: string;
  ingestedAt: string;
  seriesDescription: string;
  sliceThicknessMm: number;
  notes: string;
}

export const DEMO_STUDIES: DemoStudyEntry[] = [
  {
    code: "CT-2026-0101",
    ingestedAt: "2026-10-26 14:12 WIB",
    seriesDescription: "Non-Contrast Axial Brain CT (5.0mm)",
    sliceThicknessMm: 5.0,
    notes: "Synthetic research fixture — hyperdense focus simulated in left basal ganglia region.",
    analysis: {
      schema_version: "1.0.0",
      study: {
        study_id: "00000000-0000-4000-8000-000000000001",
        modality: "CT",
        status: "ready",
        slices: [
          {
            slice_id: "00000000-0000-4000-8000-000000000101",
            index: 0,
            image_asset_id: "00000000-0000-4000-8000-000000000201",
            z_position_mm: -15.0,
          },
          {
            slice_id: "00000000-0000-4000-8000-000000000102",
            index: 1,
            image_asset_id: "00000000-0000-4000-8000-000000000202",
            z_position_mm: -10.0,
          },
          {
            slice_id: "00000000-0000-4000-8000-000000000002",
            index: 2,
            image_asset_id: "00000000-0000-4000-8000-000000000003",
            z_position_mm: 1.5,
          },
          {
            slice_id: "00000000-0000-4000-8000-000000000104",
            index: 3,
            image_asset_id: "00000000-0000-4000-8000-000000000204",
            z_position_mm: 6.5,
          },
          {
            slice_id: "00000000-0000-4000-8000-000000000105",
            index: 4,
            image_asset_id: "00000000-0000-4000-8000-000000000205",
            z_position_mm: 11.5,
          },
        ],
      },
      findings: [
        {
          finding_id: "00000000-0000-4000-8000-000000000005",
          category: "suspected_intracranial_hemorrhage",
          evidence_slice_ids: [
            "00000000-0000-4000-8000-000000000002",
            "00000000-0000-4000-8000-000000000104",
          ],
          confidence: 0.84,
          review_status: "pending",
          model_version_id: "00000000-0000-4000-8000-000000000004",
        },
      ],
      model_version: {
        model_version_id: "00000000-0000-4000-8000-000000000004",
        provider: "demo_fixture",
        model_id: "synthetic-fixture",
        prompt_version: "demo-fixture-v1",
      },
    },
  },
  {
    code: "CT-2026-0102",
    ingestedAt: "2026-10-26 14:35 WIB",
    seriesDescription: "Head Trauma Protocol Axial CT (2.5mm)",
    sliceThicknessMm: 2.5,
    notes: "Synthetic research fixture — subtle subdural crescent attenuation along right convexity.",
    analysis: {
      schema_version: "1.0.0",
      study: {
        study_id: "00000000-0000-4000-8000-000000000010",
        modality: "CT",
        status: "ready",
        slices: [
          {
            slice_id: "00000000-0000-4000-8000-000000000301",
            index: 0,
            image_asset_id: "00000000-0000-4000-8000-000000000401",
            z_position_mm: 0.0,
          },
          {
            slice_id: "00000000-0000-4000-8000-000000000302",
            index: 1,
            image_asset_id: "00000000-0000-4000-8000-000000000402",
            z_position_mm: 2.5,
          },
          {
            slice_id: "00000000-0000-4000-8000-000000000303",
            index: 2,
            image_asset_id: "00000000-0000-4000-8000-000000000403",
            z_position_mm: 5.0,
          },
        ],
      },
      findings: [
        {
          finding_id: "00000000-0000-4000-8000-000000000015",
          category: "suspected_intracranial_hemorrhage",
          evidence_slice_ids: ["00000000-0000-4000-8000-000000000302"],
          confidence: 0.62,
          review_status: "uncertain",
          model_version_id: "00000000-0000-4000-8000-000000000004",
        },
      ],
      model_version: {
        model_version_id: "00000000-0000-4000-8000-000000000004",
        provider: "demo_fixture",
        model_id: "synthetic-fixture",
        prompt_version: "demo-fixture-v1",
      },
    },
  },
  {
    code: "CT-2026-0103",
    ingestedAt: "2026-10-26 15:02 WIB",
    seriesDescription: "Routine Non-Contrast Cranial CT (5.0mm)",
    sliceThicknessMm: 5.0,
    notes: "Synthetic research fixture — unremarkable parenchyma, no acute hyperdensity flagged.",
    analysis: {
      schema_version: "1.0.0",
      study: {
        study_id: "00000000-0000-4000-8000-000000000020",
        modality: "CT",
        status: "ready",
        slices: [
          {
            slice_id: "00000000-0000-4000-8000-000000000501",
            index: 0,
            image_asset_id: "00000000-0000-4000-8000-000000000601",
            z_position_mm: -5.0,
          },
          {
            slice_id: "00000000-0000-4000-8000-000000000502",
            index: 1,
            image_asset_id: "00000000-0000-4000-8000-000000000602",
            z_position_mm: 0.0,
          },
        ],
      },
      findings: [],
      model_version: {
        model_version_id: "00000000-0000-4000-8000-000000000004",
        provider: "demo_fixture",
        model_id: "synthetic-fixture",
        prompt_version: "demo-fixture-v1",
      },
    },
  },
  {
    code: "CT-2026-0104",
    ingestedAt: "2026-10-26 15:40 WIB",
    seriesDescription: "Emergency Stroke Triage Axial CT (1.25mm)",
    sliceThicknessMm: 1.25,
    notes: "Synthetic research fixture — currently running slice inference pipeline.",
    analysis: {
      schema_version: "1.0.0",
      study: {
        study_id: "00000000-0000-4000-8000-000000000030",
        modality: "CT",
        status: "processing",
        slices: [
          {
            slice_id: "00000000-0000-4000-8000-000000000701",
            index: 0,
            image_asset_id: "00000000-0000-4000-8000-000000000801",
            z_position_mm: 3.75,
          },
        ],
      },
      findings: [],
      model_version: {
        model_version_id: "00000000-0000-4000-8000-000000000004",
        provider: "demo_fixture",
        model_id: "synthetic-fixture",
        prompt_version: "demo-fixture-v1",
      },
    },
  },
];

export function getDemoStudyById(studyId: string): DemoStudyEntry | undefined {
  return DEMO_STUDIES.find((entry) => entry.analysis.study.study_id === studyId);
}
