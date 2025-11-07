import pandas as pd
import logging
from pathlib import Path
from typing import Dict, Any, Tuple, List

logger = logging.getLogger(__name__)


class SubmissionValidator:
    """
    Comprehensive validator for Kaggle submission files.
    Validates format, columns, data types, and sanity checks.
    """
    
    def __init__(self, submission_path: Path, competition_info: Dict[str, Any]):
        self.submission_path = submission_path
        self.competition_info = competition_info
        self.submission_schema = competition_info.get('submission_schema')
        self.data_dir = Path(competition_info['data_dir'])
        
    def validate(self) -> Tuple[bool, List[str]]:
        """
        Perform comprehensive validation of submission file.
        
        Returns:
            Tuple of (is_valid, list of error messages)
        """
        errors = []
        warnings = []
        
        try:
            # Load submission
            submission = pd.read_csv(self.submission_path)
            
            # Run all validation checks
            errors.extend(self._validate_columns(submission))
            errors.extend(self._validate_row_count(submission))
            errors.extend(self._validate_ids(submission))
            errors.extend(self._validate_target_values(submission))
            errors.extend(self._validate_null_values(submission))
            warnings.extend(self._sanity_checks(submission))
            
            # Log warnings
            for warning in warnings:
                logger.warning(f"⚠ {warning}")
            
            # Log errors
            if errors:
                logger.error("❌ Submission validation failed:")
                for error in errors:
                    logger.error(f"  - {error}")
            else:
                logger.info("✓ Submission validation passed")
            
            return (len(errors) == 0, errors)
            
        except Exception as e:
            error_msg = f"Failed to validate submission: {e}"
            logger.error(error_msg)
            return (False, [error_msg])
    
    def _validate_columns(self, submission: pd.DataFrame) -> List[str]:
        """Validate column names and order"""
        errors = []
        
        if not self.submission_schema:
            logger.warning("No submission schema available, skipping column validation")
            return errors
        
        expected_cols = self.submission_schema['expected_columns']
        actual_cols = submission.columns.tolist()
        
        # Check exact column match
        if actual_cols != expected_cols:
            errors.append(
                f"Column mismatch: Expected {expected_cols}, got {actual_cols}"
            )
        
        # Check if at least has required columns (even if order is wrong)
        missing_cols = set(expected_cols) - set(actual_cols)
        if missing_cols:
            errors.append(f"Missing required columns: {list(missing_cols)}")
        
        extra_cols = set(actual_cols) - set(expected_cols)
        if extra_cols:
            errors.append(f"Unexpected extra columns: {list(extra_cols)}")
        
        return errors
    
    def _validate_row_count(self, submission: pd.DataFrame) -> List[str]:
        """Validate number of rows matches test set"""
        errors = []
        
        if not self.submission_schema:
            return errors
        
        expected_rows = self.submission_schema['expected_rows']
        actual_rows = len(submission)
        
        if actual_rows != expected_rows:
            errors.append(
                f"Row count mismatch: Expected {expected_rows} rows, got {actual_rows}"
            )
        
        return errors
    
    def _validate_ids(self, submission: pd.DataFrame) -> List[str]:
        """Validate ID column matches test set"""
        errors = []
        
        if not self.submission_schema:
            return errors
        
        id_column = self.submission_schema['id_column']
        
        if id_column not in submission.columns:
            errors.append(f"ID column '{id_column}' not found")
            return errors
        
        # Load test file to compare IDs
        try:
            test_file = self.data_dir / 'test.csv'
            if test_file.exists():
                test_df = pd.read_csv(test_file)
                
                if id_column not in test_df.columns:
                    logger.warning(f"ID column '{id_column}' not in test.csv")
                    return errors
                
                # Check if IDs match
                submission_ids = submission[id_column].values
                test_ids = test_df[id_column].values
                
                if not (submission_ids == test_ids).all():
                    # Check if it's just an ordering issue
                    if set(submission_ids) == set(test_ids):
                        errors.append(
                            f"IDs are correct but in wrong order. "
                            f"Must match test.csv order exactly."
                        )
                    else:
                        missing_ids = set(test_ids) - set(submission_ids)
                        extra_ids = set(submission_ids) - set(test_ids)
                        
                        if missing_ids:
                            errors.append(
                                f"Missing {len(missing_ids)} IDs from test set. "
                                f"Examples: {list(missing_ids)[:5]}"
                            )
                        if extra_ids:
                            errors.append(
                                f"Found {len(extra_ids)} IDs not in test set. "
                                f"Examples: {list(extra_ids)[:5]}"
                            )
        
        except Exception as e:
            logger.warning(f"Could not validate IDs against test.csv: {e}")
        
        return errors
    
    def _validate_target_values(self, submission: pd.DataFrame) -> List[str]:
        """Validate target column values are appropriate"""
        errors = []
        
        if not self.submission_schema:
            return errors
        
        target_columns = self.submission_schema['target_columns']
        target_info = self.submission_schema['target_info']
        
        for target_col in target_columns:
            if target_col not in submission.columns:
                continue  # Already caught by column validation
            
            col_info = target_info.get(target_col, {})
            target_type = col_info.get('type')
            
            # Get actual values
            values = submission[target_col]
            unique_vals = values.unique()
            
            # Validate based on target type
            if target_type == 'binary':
                # Should be 0/1 or similar binary values
                expected_values = {0, 1}
                if not set(unique_vals).issubset(expected_values):
                    # Check if it's 1/2 or other binary encoding
                    if len(unique_vals) == 2:
                        logger.warning(
                            f"{target_col} has binary values {list(unique_vals)} "
                            f"(expected {list(expected_values)})"
                        )
                    else:
                        errors.append(
                            f"{target_col} should be binary (0/1), "
                            f"but has values: {list(unique_vals)}"
                        )
            
            elif target_type == 'multiclass':
                # Check if values are reasonable
                sample_values = col_info.get('sample_values', [])
                if sample_values:
                    # Check if predicted classes are in expected range
                    min_expected = min(sample_values) if sample_values else 0
                    max_expected = max(sample_values) if sample_values else 10
                    
                    if values.min() < min_expected or values.max() > max_expected:
                        errors.append(
                            f"{target_col} has values outside expected range "
                            f"[{min_expected}, {max_expected}]. "
                            f"Got: [{values.min()}, {values.max()}]"
                        )
            
            elif target_type == 'regression':
                # Check for reasonable regression values (not NaN, not Inf)
                if values.isnull().any():
                    errors.append(f"{target_col} contains null values")
                
                if (values == float('inf')).any() or (values == float('-inf')).any():
                    errors.append(f"{target_col} contains infinite values")
        
        return errors
    
    def _validate_null_values(self, submission: pd.DataFrame) -> List[str]:
        """Check for null values"""
        errors = []
        
        if submission.isnull().any().any():
            null_cols = submission.columns[submission.isnull().any()].tolist()
            null_counts = submission[null_cols].isnull().sum().to_dict()
            errors.append(
                f"Submission contains null values in columns: {null_counts}"
            )
        
        return errors
    
    def _sanity_checks(self, submission: pd.DataFrame) -> List[str]:
        """Perform sanity checks (return warnings, not errors)"""
        warnings = []
        
        if not self.submission_schema:
            return warnings
        
        target_columns = self.submission_schema['target_columns']
        
        for target_col in target_columns:
            if target_col not in submission.columns:
                continue
            
            values = submission[target_col]
            unique_count = values.nunique()
            
            # Check if all predictions are the same
            if unique_count == 1:
                warnings.append(
                    f"All predictions in '{target_col}' are the same value: "
                    f"{values.iloc[0]}"
                )
            
            # Check for suspiciously low variance in regression
            if self.submission_schema['target_info'].get(target_col, {}).get('type') == 'regression':
                if values.std() < 0.01:
                    warnings.append(
                        f"Very low variance in '{target_col}' (std={values.std():.6f}). "
                        f"Predictions may not be meaningful."
                    )
            
            # Check distribution makes sense
            if unique_count < 5 and len(submission) > 100:
                warnings.append(
                    f"Only {unique_count} unique predictions in '{target_col}' "
                    f"for {len(submission)} samples"
                )
        
        return warnings
    
    def get_validation_summary(self, submission: pd.DataFrame) -> str:
        """Generate a summary of the submission for logging"""
        summary = []
        summary.append(f"Submission shape: {submission.shape}")
        summary.append(f"Columns: {submission.columns.tolist()}")
        
        if self.submission_schema:
            for target_col in self.submission_schema['target_columns']:
                if target_col in submission.columns:
                    values = submission[target_col]
                    summary.append(
                        f"{target_col}: {values.nunique()} unique values, "
                        f"range [{values.min()}, {values.max()}]"
                    )
        
        return "\n".join(summary)

