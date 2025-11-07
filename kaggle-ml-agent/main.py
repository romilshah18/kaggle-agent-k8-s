#!/usr/bin/env python3
import argparse
import sys
import logging
from pathlib import Path

from agent.analyzer.competition_analyzer import CompetitionAnalyzer
from agent.planner.strategy_planner import StrategyPlanner
from agent.generator.code_generator import CodeGenerator
from agent.executor.model_executor import ModelExecutor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Autonomous Kaggle Competition Agent')
    parser.add_argument('--job-id', required=True, help='Job ID')
    parser.add_argument('--url', required=True, help='Kaggle competition URL')
    args = parser.parse_args()
    
    job_id = args.job_id
    kaggle_url = args.url
    # Output to /shared/submissions/{job_id} which is mounted from the host
    output_dir = Path(f"/shared/submissions/{job_id}")
    
    logger.info("="*60)
    logger.info(f"KAGGLE AGENT STARTED")
    logger.info(f"Job ID: {job_id}")
    logger.info(f"Competition URL: {kaggle_url}")
    logger.info("="*60)
    
    try:
        # Stage 1: Analyze Competition
        logger.info("\n[STAGE 1] Analyzing competition...")
        logger.info(f"Competition URL: {kaggle_url}")
        logger.info(f"Data and outputs will be stored in: {output_dir}")
        
        # Pass output_dir so data is stored with the submission
        analyzer = CompetitionAnalyzer(kaggle_url, data_dir=str(output_dir))
        competition_info = analyzer.analyze()
        
        # Enhanced logging
        logger.info(f"✓ Competition: {competition_info['name']}")
        logger.info(f"✓ Task Type: {competition_info['task_type']}")
        logger.info(f"✓ Data Files: {len(competition_info['data_files'])} files")
        logger.info(f"✓ Evaluation Metric: {competition_info.get('metric', 'unknown')}")
        logger.info(f"✓ Target Column: {competition_info.get('target_column', 'N/A')}")
        
        # Log submission schema if available
        if competition_info.get('submission_schema'):
            schema = competition_info['submission_schema']
            logger.info(f"✓ Submission Format:")
            logger.info(f"  - Columns: {schema.get('expected_columns', [])}")
            logger.info(f"  - ID Column: {schema.get('id_column', 'N/A')}")
            logger.info(f"  - Target Columns: {schema.get('target_columns', [])}")
            logger.info(f"  - Expected Rows: {schema.get('expected_rows', 'N/A')}")
        else:
            logger.warning("⚠ No submission schema detected")
        
        # Stage 2: Plan Strategy
        logger.info("\n[STAGE 2] Planning strategy...")
        planner = StrategyPlanner(competition_info)
        strategy = planner.create_strategy()
        
        logger.info(f"✓ Approach: {strategy['approach']}")
        logger.info(f"✓ Models: {', '.join(strategy['models'])}")
        logger.info(f"✓ Features: {strategy['feature_engineering']}")
        
        # Stage 3: Generate Code
        logger.info("\n[STAGE 3] Generating code with validation...")
        generator = CodeGenerator(competition_info, strategy, str(output_dir))
        code = generator.generate()
        
        # Save generated code
        code_path = output_dir / "generated_solution.py"
        with open(code_path, 'w') as f:
            f.write(code)
        logger.info(f"✓ Code saved to {code_path}")
        logger.info(f"✓ Code length: {len(code)} characters, {len(code.split(chr(10)))} lines")
        
        # Stage 4: Execute Training
        logger.info("\n[STAGE 4] Training model and creating submission...")
        executor = ModelExecutor(competition_info, code_path, output_dir)
        submission_path = executor.execute()
        
        if submission_path and submission_path.exists():
            # Additional validation logging
            import pandas as pd
            try:
                sub_df = pd.read_csv(submission_path)
                logger.info(f"✓ Submission created: {submission_path}")
                logger.info(f"✓ Submission shape: {sub_df.shape}")
                logger.info(f"✓ Submission columns: {sub_df.columns.tolist()}")
                
                # Log sample of submission
                logger.info(f"✓ Submission preview:")
                for idx, row in sub_df.head(3).iterrows():
                    logger.info(f"  Row {idx}: {row.to_dict()}")
                
            except Exception as e:
                logger.warning(f"Could not read submission for logging: {e}")
            
            logger.info("\n" + "="*60)
            logger.info("SUCCESS: Agent completed successfully!")
            logger.info("="*60)
            return 0
        else:
            logger.error("✗ Failed to create valid submission.csv")
            logger.error("Check logs above for validation errors")
            return 1
            
    except Exception as e:
        logger.error(f"\n{'='*60}")
        logger.error(f"FAILURE: {str(e)}")
        logger.error(f"{'='*60}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

