# RSNA Brain CT Hemorrhage dataset: licensing and profile

**RADAR AI / RDA-2 — Sprint 1**  
**Prepared:** 2026-10-26 (WIB)  
**Status:** Source assessment complete; local data profile pending dataset access  
**Scope:** Research prototype only — **NOT FOR CLINICAL USE**

## Dataset identity and provenance

This assessment concerns the **RSNA Intracranial Hemorrhage Detection / RSNA 2019 Brain CT Hemorrhage Challenge** dataset. It contains de-identified axial, non-contrast head CT DICOM images and expert labels. RSNA reports more than 25,000 annotated exams; the data resource paper reports 874,035 images. The RSNA dataset description says images are 512 × 512 and 5 mm slice thickness, with one contributing site resampled to 5 mm. These are published dataset-level facts, not counts verified against a local copy.

The Kaggle challenge's training label schema contains six image-level targets: `any`, `epidural`, `intraparenchymal`, `intraventricular`, `subarachnoid`, and `subdural` hemorrhage. Each image has one row per target; `any` is a derived umbrella target. This schema should not be mistaken for six mutually exclusive classes: multiple subtype labels can be positive for an image. RSNA also describes exam-level annotations and curation labels such as incomplete exam, needs adjudication, ignore series, and question; those are not the six Kaggle prediction targets.

## License and usage assessment

RSNA's published terms describe use for **academic research, education, and other non-commercial purposes**. They prohibit attempts to identify or contact people represented in the data. RSNA's AWS Open Data Registry additionally says that no portion or copy of the data may be shared or redistributed. The RSNA-hosted terms PDF instead describes attribution requirements in the event of sharing or redistribution. Because these official statements differ, this project adopts the stricter operational rule: **do not redistribute the images, labels, or any portion of the dataset** unless RSNA provides written clarification/authorization. Keep any authorized dataset copy in approved private storage; do not commit, attach, or publish it in this repository, a PR, demo, or artifact.

Additional requirements and limits:

- Treat the dataset as non-commercial. A hackathon prototype or any later monetized, commercial, or production use is not cleared by this assessment; obtain written rights confirmation before such use.
- Never attempt re-identification or contact with subjects. “De-identified” does not mean risk-free; do not publish DICOM headers or potentially identifying metadata.
- Cite the dataset in publications and public summaries: Flanders AF, Prevedello LM, Shih G, et al. *Construction of a Machine Learning Dataset through Collaboration: The RSNA 2019 Brain CT Hemorrhage Challenge*. *Radiology: Artificial Intelligence*. 2020;2(3). doi: [10.1148/ryai.2020190211](https://doi.org/10.1148/ryai.2020190211). Also link the [RSNA dataset and annotation page](https://www.rsna.org/artificial-intelligence/ai-image-challenge/RSNA-Intracranial-Hemorrhage-Detection-Challenge-2019).
- Dataset access through Kaggle is subject to the competition rules and requires agreement to those rules. The AWS registry describes the source as a zip archive of DICOM and CSV files in a controlled-access S3 bucket.
- This assessment is an engineering interpretation of the published terms, not legal advice. The differing redistribution language and any intended commercial use require clarification from RSNA (`informatics@rsna.org`).

## Profile and count status

No RSNA DICOM, Kaggle labels CSV, or dataset mount was present in the repository/workspace when this assessment was prepared. Therefore, the following **local** counts and distributions have not been computed:

| Measure | Local result | Notes |
| --- | ---: | --- |
| Labeled studies / exams | Not available | No DICOMs or study manifest supplied; do not infer this from slice count. |
| Labeled slices / images | Not available | No labels CSV or DICOM files supplied. |
| Per-target positive/negative counts | Not available | Requires the exact labels CSV; report `any` and each subtype independently. |
| Multi-positive slices | Not available | Labels overlap; do not sum subtype positives as a partition. |

For context only, RSNA's publication reports **874,035 images** and RSNA's challenge page reports **more than 25,000 annotated cranial CT exams**. These are published aggregate figures and must not be represented as counts from RADAR AI's copy. A reproducible local profile remains a handoff dependency: obtain an authorized dataset copy, keep it outside version control, record its source version and file checksums privately, then compute study counts from DICOM `StudyInstanceUID` and slice/label counts from the supplied labels. Do not put patient or DICOM identifiers into the public report or manifest.

## Immutable source manifest

The versioned machine-readable source record is [rsna-ich-source-manifest.json](./rsna-ich-source-manifest.json). It records origin, source URLs, source revision, access date, terms summary, and explicit unavailable local fingerprints/counts. It contains no patient-level metadata. Treat each revision as append-only: create a new manifest version when source files are acquired or source terms change; do not silently replace a recorded source snapshot. The manifest is provenance metadata, not proof that this workspace holds or is licensed to redistribute the data.

## Handoff

**Dependent workstream:** data ingestion/modeling. This report and manifest define the label schema, non-commercial boundary, attribution, and the profiling dependency. Before model training or any demo using RSNA data, the receiving workstream must confirm authorized access and non-commercial scope. Local counts and class distribution remain blocked on delivery of the approved source files to private storage.

## Sources

- [RSNA Intracranial Hemorrhage Detection Challenge (2019)](https://www.rsna.org/artificial-intelligence/ai-image-challenge/RSNA-Intracranial-Hemorrhage-Detection-Challenge-2019)
- [RSNA Terms of Use and Attribution (PDF)](https://www.rsna.org/-/media/files/rsna/education/ai-resources-and-training/ai-image-challenge/rsna_ich_ai_challenge_2019_terms_of_use_and_attribution_final.pdf)
- [AWS Open Data Registry entry](https://registry.opendata.aws/rsna-intracranial-hemorrhage-detection/)
- [RSNA dataset description (PDF)](https://www.rsna.org/education/%20ai-resources-and-training/-/media/Files/RSNA/Education/AI%20resources%20and%20training/AI%20image%20challenge/RSNA-2019-Brain-Hemorrhage-Detection-Challenge-Dataset-Description.ashx)
- [Kaggle challenge data page](https://www.kaggle.com/c/rsna-intracranial-hemorrhage-detection/data)
- [Dataset publication](https://doi.org/10.1148/ryai.2020190211)

