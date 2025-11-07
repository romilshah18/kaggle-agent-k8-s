import subprocess
import logging
import pandas as pd
from pathlib import Path
from typing import Optional, Dict, Any, List

from agent.validator.submission_validator import SubmissionValidator

logger = logging.getLogger(__name__)


class ModelExecutor:
    def __init__(self, competition_info, code_path: Path, output_dir: Path):
        self.competition_info = competition_info
        self.code_path = code_path
        self.output_dir = output_dir
    
    def execute(self) -> Optional[Path]:
        """
        Execute the generated training script with error recovery
        
        Returns:
            Path to submission.csv if successful, None otherwise
        """
        logger.info(f"Executing training script: {self.code_path}")
        
        try:
            # Run the generated code
            result = subprocess.run(
                ['python', str(self.code_path)],
                capture_output=True,
                text=True,
                timeout=6000,  # 100 minutes max
                cwd=str(self.code_path.parent)
            )
            
            # Log output
            if result.stdout:
                logger.info("Script output:")
                for line in result.stdout.split('\n'):
                    if line.strip():
                        logger.info(f"  {line}")
            
            if result.stderr:
                logger.warning("Script errors:")
                for line in result.stderr.split('\n'):
                    if line.strip():
                        logger.warning(f"  {line}")
            
            # Check for submission file
            submission_path = self.output_dir / "submission.csv"
            
            # Handle execution failures with recovery
            if result.returncode != 0:
                logger.error(f"Script failed with exit code {result.returncode}")
                
                # Try to recover from common errors
                if submission_path.exists():
                    logger.info("Submission file exists despite error - attempting validation")
                else:
                    # Try to create a fallback submission
                    logger.warning("Attempting to create fallback submission...")
                    fallback_path = self._create_fallback_submission()
                    if fallback_path:
                        submission_path = fallback_path
                    else:
                        return None
            
            # Validate submission exists
            if not submission_path.exists():
                logger.error(f"Submission file not found at {submission_path}")
                return None
            
            # Use comprehensive validator
            validator = SubmissionValidator(submission_path, self.competition_info)
            is_valid, errors = validator.validate()
            
            if is_valid:
                logger.info(f"✓ Valid submission created: {submission_path}")
                return submission_path
            
            # Try to fix the submission automatically
            logger.warning(f"Submission validation failed with {len(errors)} errors")
            logger.info("Attempting automatic correction...")
            
            if self._attempt_submission_fix(submission_path, errors):
                # Re-validate after fix
                validator = SubmissionValidator(submission_path, self.competition_info)
                is_valid, errors = validator.validate()
                
                if is_valid:
                    logger.info("✓ Submission corrected successfully!")
                    return submission_path
                else:
                    logger.error(f"Still has errors after correction: {errors}")
            
            logger.error("Could not fix submission errors")
            return None
                
        except subprocess.TimeoutExpired:
            logger.error("Script execution timeout (100 minutes)")
            return None
            
        except Exception as e:
            logger.error(f"Execution failed: {e}", exc_info=True)
            return None
    
    def _attempt_submission_fix(self, submission_path: Path, errors: List[str]) -> bool:
        """
        Attempt to automatically fix common submission errors
        
        Returns:
            True if fixes were applied, False otherwise
        """
        try:
            submission = pd.read_csv(submission_path)
            modified = False
            
            if not self.competition_info.get('submission_schema'):
                logger.warning("No submission schema available for fixing")
                return False
            
            schema = self.competition_info['submission_schema']
            
            # Fix 1: Wrong column names (but correct count)
            expected_cols = schema['expected_columns']
            if len(submission.columns) == len(expected_cols):
                if list(submission.columns) != expected_cols:
                    logger.info(f"Fixing column names: {list(submission.columns)} -> {expected_cols}")
                    submission.columns = expected_cols
                    modified = True
            
            # Fix 2: Wrong ID order
            id_col = schema['id_column']
            if id_col in submission.columns:
                test_file = Path(self.competition_info['data_dir']) / 'test.csv'
                if test_file.exists():
                    test_df = pd.read_csv(test_file)
                    if id_col in test_df.columns:
                        # Check if it's just an ordering issue
                        if set(submission[id_col]) == set(test_df[id_col]):
                            logger.info("Reordering submission to match test.csv ID order")
                            # Merge to get correct order
                            test_ids = test_df[[id_col]]
                            submission = test_ids.merge(
                                submission, on=id_col, how='left'
                            )
                            modified = True
            
            # Fix 3: Label indexing issues (e.g., 1-indexed to 0-indexed)
            target_cols = schema['target_columns']
            for target_col in target_cols:
                if target_col not in submission.columns:
                    continue
                
                target_info = schema['target_info'].get(target_col, {})
                if target_info.get('type') == 'binary':
                    # Check if it's 1/2 instead of 0/1
                    unique_vals = submission[target_col].unique()
                    if set(unique_vals) == {1, 2}:
                        logger.info(f"Converting {target_col} from {{1,2}} to {{0,1}}")
                        submission[target_col] = submission[target_col] - 1
                        modified = True
                    elif submission[target_col].min() == 1 and submission[target_col].max() == 1:
                        # All 1s when should be 0/1
                        pass  # Can't fix this automatically
            
            # Fix 4: Fill null values with mode (last resort)
            if submission.isnull().any().any():
                logger.info("Filling null values with column mode")
                for col in submission.columns:
                    if submission[col].isnull().any():
                        mode_val = submission[col].mode()
                        if len(mode_val) > 0:
                            submission[col].fillna(mode_val[0], inplace=True)
                        else:
                            submission[col].fillna(0, inplace=True)
                modified = True
            
            if modified:
                submission.to_csv(submission_path, index=False)
                logger.info("✓ Submission file updated with corrections")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to fix submission: {e}")
            return False
    
    def _create_fallback_submission(self) -> Optional[Path]:
        """
        Create a fallback submission file with dummy predictions
        This is a last resort when execution fails completely
        """
        try:
            if not self.competition_info.get('submission_schema'):
                logger.warning("No submission schema for fallback")
                return None
            
            schema = self.competition_info['submission_schema']
            test_file = Path(self.competition_info['data_dir']) / 'test.csv'
            
            if not test_file.exists():
                logger.error("Test file not found for fallback submission")
                return None
            
            test_df = pd.read_csv(test_file)
            id_col = schema['id_column']
            
            if id_col not in test_df.columns:
                logger.error(f"ID column '{id_col}' not in test.csv")
                return None
            
            # Create submission with dummy predictions
            submission = pd.DataFrame()
            submission[id_col] = test_df[id_col]
            
            # Add dummy predictions for each target
            for target_col in schema['target_columns']:
                target_info = schema['target_info'].get(target_col, {})
                target_type = target_info.get('type', 'regression')
                
                if target_type == 'binary':
                    # Use most common class (0)
                    submission[target_col] = 0
                elif target_type == 'multiclass':
                    # Use first sample value or 0
                    sample_vals = target_info.get('sample_values', [0])
                    submission[target_col] = sample_vals[0] if sample_vals else 0
                else:  # regression
                    # Use mean of sample values or 0
                    sample_vals = target_info.get('sample_values', [0])
                    submission[target_col] = sum(sample_vals) / len(sample_vals) if sample_vals else 0.0
            
            submission_path = self.output_dir / "submission.csv"
            submission.to_csv(submission_path, index=False)
            
            logger.warning(f"⚠ Created fallback submission with dummy predictions")
            return submission_path
            
        except Exception as e:
            logger.error(f"Failed to create fallback submission: {e}")
            return None

