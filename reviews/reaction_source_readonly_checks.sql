-- Read-only source assessment. Connection credentials are supplied externally.
\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '20s';
SET LOCAL lock_timeout = '2s';

SELECT current_setting('transaction_read_only') AS read_only,
       rdkit_toolkit_version() AS toolkit_version,
       rdkit_version() AS cartridge_version;

SELECT count(*) AS reactions,
       count(DISTINCT (source_namespace, document_id)) AS documents,
       count(*) FILTER (WHERE reaction_class IS NOT NULL) AS with_class,
       count(*) FILTER (WHERE reaction_center_r1 IS NOT NULL) AS with_template,
       count(*) FILTER (WHERE temperature_min_c IS NOT NULL OR temperature_max_c IS NOT NULL) AS with_temperature,
       count(*) FILTER (WHERE duration_min_seconds IS NOT NULL OR duration_max_seconds IS NOT NULL) AS with_duration,
       count(*) FILTER (WHERE pressure_min_kpa IS NOT NULL OR pressure_max_kpa IS NOT NULL) AS with_pressure,
       count(*) FILTER (WHERE yield_min_pct IS NOT NULL OR yield_max_pct IS NOT NULL) AS with_yield
FROM reaction.reactions;

SELECT count(*) AS evidence_links,
       count(*) FILTER (WHERE text IS NULL OR btrim(text) = '') AS missing_text
FROM reaction.evidence;

SELECT size(product_fp) AS stored_product_bits,
       size(reactant_fp) AS stored_reactant_bits, count(*) AS records
FROM reaction.reactions GROUP BY 1, 2;

SELECT current_setting('rdkit.morgan_fp_size') AS connection_morgan_bits,
       current_setting('rdkit.do_chiral_sss') AS chiral_substructure_search,
       current_setting('rdkit.do_enhanced_stereo_sss') AS enhanced_stereo_search;

SELECT size(morganbv_fp(products_mol, 2)) AS default_query_bits
FROM reaction.reactions ORDER BY id LIMIT 1;

-- A synthetic semantic counterexample; it is not a source reaction.
SELECT 'CO.CN'::mol @> 'O.N'::qmol AS disconnected_query_crosses_molecules;

SELECT count(*) AS example_substructure_hits
FROM reaction.reactions WHERE products_mol @> 'c1nnco1'::qmol;
EXPLAIN (COSTS OFF)
SELECT id FROM reaction.reactions WHERE products_mol @> 'c1nnco1'::qmol ORDER BY id LIMIT 20;

-- Session-local test only. COMMIT restores the prior setting.
SET LOCAL rdkit.morgan_fp_size = 2048;
SELECT count(*) AS checked,
       count(*) FILTER (WHERE bfp_to_binary_text(product_fp) =
           bfp_to_binary_text(morganbv_fp(products_mol, 2))) AS matching_product_fingerprints,
       count(*) FILTER (WHERE bfp_to_binary_text(reactant_fp) =
           bfp_to_binary_text(morganbv_fp(reactants_mol, 2))) AS matching_reactant_fingerprints
FROM reaction.reactions;
COMMIT;
