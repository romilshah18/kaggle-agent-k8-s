import anthropic
import os
import ast
import logging
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


class CodeGenerator:
    def __init__(self, competition_info: Dict[str, Any], strategy: Dict[str, Any], output_dir: str = "/output"):
        self.competition_info = competition_info
        self.strategy = strategy
        self.output_dir = output_dir
        self.client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        
        # Get available libraries from environment or use defaults
        self.available_libs = self._get_available_libraries()
        logger.info(f"Available libraries for code generation: {self.available_libs}")
    
    def generate(self) -> str:
        """Generate complete training script with feedback loop"""
        logger.info("Generating code with Claude (multi-attempt with validation)...")
        
        # Try LLM generation with feedback loop
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            logger.info(f"Generation attempt {attempt}/{max_attempts}")
            
            try:
                # Generate code
                if attempt == 1:
                    code = self._generate_with_llm()
                else:
                    # Regenerate with feedback from previous attempt
                    code = self._generate_with_llm(feedback=feedback_msg)
                
                # Validate generated code
                is_valid, validation_errors = self._validate_generated_code(code)
                
                if is_valid:
                    logger.info(f"✓ Code generated and validated successfully on attempt {attempt}")
                    return code
                else:
                    logger.warning(f"Code validation failed on attempt {attempt}:")
                    for error in validation_errors:
                        logger.warning(f"  - {error}")
                    
                    # Prepare feedback for next attempt
                    feedback_msg = self._format_feedback(validation_errors)
                    
                    if attempt == max_attempts:
                        logger.warning("Max attempts reached, using best generated code")
                        return code
                    
            except Exception as e:
                logger.warning(f"LLM generation attempt {attempt} failed: {e}")
                if attempt == max_attempts:
                    logger.warning("All LLM attempts failed, falling back to template")
                    return self._generate_from_template()
        
        # Fallback to template
        logger.warning("Generation failed, using template")
        return self._generate_from_template()
    
    def _generate_with_llm(self, feedback: str = None) -> str:
        """
        Generate code using Claude with optional feedback from previous attempt
        
        Args:
            feedback: Optional feedback from validation failures
        """
        # Enhanced prompt with submission schema
        submission_schema = self.competition_info.get('submission_schema', {})
        
        # Build submission format instructions
        submission_format = ""
        if submission_schema:
            submission_format = f"""
CRITICAL SUBMISSION FORMAT REQUIREMENTS:
Your submission.csv MUST have EXACTLY these columns in this order:
{submission_schema.get('expected_columns', [])}

Details:
- ID Column: {submission_schema.get('id_column')} (copy from test.csv)
- Target Column(s): {submission_schema.get('target_columns', [])}
- Expected Rows: {submission_schema.get('expected_rows')}
- Target Types: {submission_schema.get('target_info', {})}

Example submission format (first row):
ID Column: {submission_schema.get('id_column')}, Target: {submission_schema.get('target_columns')}
"""
        
        feedback_section = ""
        if feedback:
            feedback_section = f"""
IMPORTANT - Previous attempt had issues:
{feedback}

Please fix these issues in your generated code.
"""
        
        prompt = f"""
Generate a complete Python script for a Kaggle competition.

Competition Details:
- Name: {self.competition_info['name']}
- Task: {self.competition_info['task_type']}
- Metric: {self.competition_info['metric']}
- Target Column in train.csv: {self.competition_info.get('target_column')}
- Data directory: {self.competition_info['data_dir']}

{submission_format}

Strategy:
- Approach: {self.strategy['approach']}
- Models: {', '.join(self.strategy['models'])}
- Feature Engineering: {self.strategy['feature_engineering']}

{feedback_section}

Requirements:
1. Load train.csv and test.csv from {self.competition_info['data_dir']}
2. The target column to predict is: {self.competition_info.get('target_column')}
3. Handle missing values appropriately
4. Encode categorical features properly
5. Train {self.strategy['models'][0]} model
6. Make predictions on test set
7. Create submission DataFrame with EXACT columns: {submission_schema.get('expected_columns', [])}
8. Ensure ID column matches test.csv exactly (same order)
9. Save to: {self.output_dir}/submission.csv (CRITICAL path)
10. Include proper error handling and progress messages

IMPORTANT CODE REQUIREMENTS:
- Use os.makedirs("{self.output_dir}", exist_ok=True) to ensure output directory exists
- Reference target column as: {self.competition_info.get('target_column')}
- For submission, use test IDs from: test_df['{submission_schema.get('id_column', 'id')}']
- Submission must be saved to exactly: {self.output_dir}/submission.csv

AVAILABLE LIBRARIES:
You can use any of these libraries (they are pre-installed):
{self.available_libs}

The script must be self-contained and executable. Import only what you need from the above list.
"""
        
        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        content = response.content[0].text
        
        # Extract code block
        if '```python' in content:
            code = content.split('```python')[1].split('```')[0].strip()
        elif '```' in content:
            code = content.split('```')[1].split('```')[0].strip()
        else:
            code = content
        
        return code
    
    def _validate_generated_code(self, code: str) -> Tuple[bool, List[str]]:
        """
        Validate generated code before execution (static analysis)
        
        Returns:
            Tuple of (is_valid, list of errors)
        """
        errors = []
        
        # Check 1: Syntax validation
        try:
            ast.parse(code)
        except SyntaxError as e:
            errors.append(f"Syntax error: {e}")
            return (False, errors)
        
        # Check 2: Required imports
        required_imports = ['pandas', 'numpy']
        for imp in required_imports:
            if imp not in code and f"import {imp}" not in code:
                errors.append(f"Missing required import: {imp}")
        
        # Check 3: Target column reference
        target_col = self.competition_info.get('target_column')
        if target_col and target_col not in code:
            errors.append(f"Target column '{target_col}' not referenced in code")
        
        # Check 4: Submission path
        expected_path = f"{self.output_dir}/submission.csv"
        if expected_path not in code and "submission.csv" not in code:
            errors.append(f"Submission path not found in code")
        
        # Check 5: Submission schema columns
        submission_schema = self.competition_info.get('submission_schema')
        if submission_schema:
            id_col = submission_schema.get('id_column')
            target_cols = submission_schema.get('target_columns', [])
            
            if id_col and id_col not in code:
                errors.append(f"ID column '{id_col}' not referenced in code")
            
            for tcol in target_cols:
                if tcol not in code:
                    errors.append(f"Target column '{tcol}' not referenced in code")
        
        # Check 6: Data loading
        data_dir = self.competition_info.get('data_dir', '')
        if data_dir and data_dir not in code:
            errors.append(f"Data directory '{data_dir}' not found in code")
        
        # Check 7: Basic ML workflow present
        workflow_keywords = ['fit', 'predict', 'to_csv']
        missing_workflow = [kw for kw in workflow_keywords if kw not in code]
        if missing_workflow:
            errors.append(f"Missing ML workflow steps: {missing_workflow}")
        
        return (len(errors) == 0, errors)
    
    def _format_feedback(self, validation_errors: List[str]) -> str:
        """Format validation errors as feedback for LLM"""
        feedback = "The generated code has the following issues:\n\n"
        for i, error in enumerate(validation_errors, 1):
            feedback += f"{i}. {error}\n"
        
        feedback += "\nPlease regenerate the code fixing ALL of these issues."
        
        # Add specific guidance based on errors
        if any('target column' in err.lower() for err in validation_errors):
            target_col = self.competition_info.get('target_column')
            feedback += f"\n\nREMINDER: The target column name is '{target_col}' - use this exact name."
        
        if any('submission' in err.lower() for err in validation_errors):
            submission_schema = self.competition_info.get('submission_schema', {})
            feedback += f"\n\nREMINDER: Submission must have columns: {submission_schema.get('expected_columns', [])}"
        
        return feedback
    
    def _get_available_libraries(self) -> str:
        """
        Get list of available libraries from environment or use defaults
        
        Returns:
            Comma-separated string of available library names
        """
        # Try to get from environment variable (set in Dockerfile)
        env_libs = os.getenv('AGENT_AVAILABLE_LIBS')
        
        if env_libs:
            return env_libs
        
        # Fallback to hardcoded list (for backward compatibility)
        default_libs = [
            'pandas', 'numpy', 'scipy',
            'scikit-learn', 'xgboost', 'lightgbm', 'catboost',
            'optuna', 'nltk', 'textblob',
            'pillow', 'opencv-python', 'statsmodels',
            'tqdm', 'joblib', 'matplotlib', 'seaborn'
        ]
        
        return ', '.join(default_libs)
    
    def _generate_from_template(self) -> str:
        """Generate from template (fallback)"""
        task_type = self.competition_info['task_type']
        target_col = self.competition_info.get('target_column', 'target')
        data_dir = self.competition_info['data_dir']
        
        if task_type == 'classification':
            return self._classification_template(data_dir, target_col)
        else:
            return self._regression_template(data_dir, target_col)
    
    def _classification_template(self, data_dir: str, target_col: str) -> str:
        # Use submission schema in templates
        submission_schema = self.competition_info.get('submission_schema', {})
        id_col = submission_schema.get('id_column', 'id')
        target_cols = submission_schema.get('target_columns', [target_col])
        target_col_output = target_cols[0] if target_cols else target_col
        
        return f'''
import pandas as pd
import numpy as np
from sklearn.model_selection import cross_val_score, StratifiedKFold
from sklearn.preprocessing import LabelEncoder
from lightgbm import LGBMClassifier
import warnings
import os
warnings.filterwarnings('ignore')

print("Loading data...")
train = pd.read_csv("{data_dir}/train.csv")
test = pd.read_csv("{data_dir}/test.csv")
print(f"Train shape: {{train.shape}}, Test shape: {{test.shape}}")

# Ensure output directory exists
os.makedirs("{self.output_dir}", exist_ok=True)

# Use submission schema for correct column names
id_col = "{id_col}"
target_col = "{target_col}"  # Target in train.csv
target_col_submission = "{target_col_output}"  # Target in submission.csv

# Verify target exists in train
if target_col not in train.columns:
    print(f"Warning: Target '{{target_col}}' not in train. Looking for alternatives...")
    for col in train.columns:
        if col not in test.columns and col.lower() != id_col.lower():
            target_col = col
            print(f"Using '{{target_col}}' as target")
            break

# Extract IDs and features
test_ids = test[id_col].copy()
X = train.drop([target_col, id_col] if id_col in train.columns else [target_col], axis=1, errors='ignore')
y = train[target_col]
X_test = test.drop([id_col], axis=1, errors='ignore')
print(f"Features: {{X.shape[1]}}, Target: {{target_col}}")

# Handle missing values
print("Handling missing values...")
for col in X.columns:
    if X[col].dtype == 'object':
        X[col].fillna('missing', inplace=True)
        if col in X_test.columns:
            X_test[col].fillna('missing', inplace=True)
    else:
        X[col].fillna(X[col].median(), inplace=True)
        if col in X_test.columns:
            X_test[col].fillna(X_test[col].median(), inplace=True)

# Encode categorical variables
print("Encoding categorical variables...")
for col in X.columns:
    if col not in X_test.columns:
        continue
    if X[col].dtype == 'object':
        le = LabelEncoder()
        X[col] = le.fit_transform(X[col].astype(str))
        X_test[col] = le.transform(X_test[col].astype(str))

# Encode target if categorical
if y.dtype == 'object':
    le_target = LabelEncoder()
    y = le_target.fit_transform(y)

print("Training model...")
model = LGBMClassifier(
    n_estimators=500,
    learning_rate=0.05,
    max_depth=7,
    num_leaves=31,
    random_state=42,
    verbose=-1
)

# Cross-validation
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
cv_scores = cross_val_score(model, X, y, cv=cv, scoring='accuracy', n_jobs=-1)
print(f"CV Accuracy: {{cv_scores.mean():.4f}} (+/- {{cv_scores.std():.4f}})")

# Train on full data
model.fit(X, y)
print("Model trained successfully")

# Predict
print("Making predictions...")
predictions = model.predict(X_test)

# Create submission with exact column names from schema
submission = pd.DataFrame({{
    id_col: test_ids,
    target_col_submission: predictions
}})

submission.to_csv("{self.output_dir}/submission.csv", index=False)
print("✓ Submission saved to {self.output_dir}/submission.csv")
print(f"Submission shape: {{submission.shape}}")
print(f"Columns: {{submission.columns.tolist()}}")
print(submission.head())
'''

    def _regression_template(self, data_dir: str, target_col: str) -> str:
        # Use submission schema in templates
        submission_schema = self.competition_info.get('submission_schema', {})
        id_col = submission_schema.get('id_column', 'id')
        target_cols = submission_schema.get('target_columns', [target_col])
        target_col_output = target_cols[0] if target_cols else target_col
        
        return f'''
import pandas as pd
import numpy as np
from sklearn.model_selection import cross_val_score, KFold
from sklearn.preprocessing import LabelEncoder
from lightgbm import LGBMRegressor
import warnings
import os
warnings.filterwarnings('ignore')

print("Loading data...")
train = pd.read_csv("{data_dir}/train.csv")
test = pd.read_csv("{data_dir}/test.csv")
print(f"Train shape: {{train.shape}}, Test shape: {{test.shape}}")

# Ensure output directory exists
os.makedirs("{self.output_dir}", exist_ok=True)

# Use submission schema for correct column names
id_col = "{id_col}"
target_col = "{target_col}"  # Target in train.csv
target_col_submission = "{target_col_output}"  # Target in submission.csv

# Verify target exists in train
if target_col not in train.columns:
    print(f"Warning: Target '{{target_col}}' not in train. Looking for alternatives...")
    for col in train.columns:
        if col not in test.columns and col.lower() != id_col.lower():
            target_col = col
            print(f"Using '{{target_col}}' as target")
            break

# Extract IDs and features
test_ids = test[id_col].copy()
X = train.drop([target_col, id_col] if id_col in train.columns else [target_col], axis=1, errors='ignore')
y = train[target_col]
X_test = test.drop([id_col], axis=1, errors='ignore')
print(f"Features: {{X.shape[1]}}, Target: {{target_col}}")

# Handle missing values
print("Handling missing values...")
for col in X.columns:
    if X[col].dtype == 'object':
        X[col].fillna('missing', inplace=True)
        if col in X_test.columns:
            X_test[col].fillna('missing', inplace=True)
    else:
        X[col].fillna(X[col].median(), inplace=True)
        if col in X_test.columns:
            X_test[col].fillna(X_test[col].median(), inplace=True)

# Encode categorical variables
print("Encoding categorical variables...")
for col in X.columns:
    if col not in X_test.columns:
        continue
    if X[col].dtype == 'object':
        le = LabelEncoder()
        X[col] = le.fit_transform(X[col].astype(str))
        X_test[col] = le.transform(X_test[col].astype(str))

print("Training model...")
model = LGBMRegressor(
    n_estimators=500,
    learning_rate=0.05,
    max_depth=7,
    num_leaves=31,
    random_state=42,
    verbose=-1
)

# Cross-validation
cv = KFold(n_splits=5, shuffle=True, random_state=42)
cv_scores = cross_val_score(model, X, y, cv=cv, scoring='neg_root_mean_squared_error', n_jobs=-1)
print(f"CV RMSE: {{-cv_scores.mean():.4f}} (+/- {{cv_scores.std():.4f}})")

# Train on full data
model.fit(X, y)
print("Model trained successfully")

# Predict
print("Making predictions...")
predictions = model.predict(X_test)

# Create submission with exact column names from schema
submission = pd.DataFrame({{
    id_col: test_ids,
    target_col_submission: predictions
}})

submission.to_csv("{self.output_dir}/submission.csv", index=False)
print("✓ Submission saved to {self.output_dir}/submission.csv")
print(f"Submission shape: {{submission.shape}}")
print(f"Columns: {{submission.columns.tolist()}}")
print(submission.head())
'''

