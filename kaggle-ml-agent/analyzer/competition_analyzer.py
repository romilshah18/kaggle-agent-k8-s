import requests
from bs4 import BeautifulSoup
import pandas as pd
import os
import zipfile
from pathlib import Path
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class CompetitionAnalyzer:
    def __init__(self, kaggle_url: str, data_dir: str = None):
        """
        Initialize Competition Analyzer
        
        Args:
            kaggle_url: URL to the Kaggle competition
            data_dir: Optional directory to store data. If None, uses /tmp/{competition_name}
        """
        self.kaggle_url = kaggle_url
        self.competition_name = kaggle_url.rstrip('/').split('/')[-1]
        
        # Use provided data_dir or default to /tmp
        if data_dir:
            self.data_dir = Path(data_dir) / "data"
        else:
            self.data_dir = Path(f"/tmp/{self.competition_name}")
        
        self.data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Data will be stored in: {self.data_dir}")
        
    def analyze(self) -> Dict[str, Any]:
        """
        Analyze competition and return structured information
        """
        logger.info(f"Analyzing competition: {self.competition_name}")
        
        # Download competition data
        self._download_data()
        
        # Analyze data files
        data_info = self._analyze_data_files()
        
        # Scrape competition page for metadata
        metadata = self._scrape_competition_page()
        
        # Determine task type
        task_type = self._determine_task_type(data_info, metadata)
        
        return {
            "name": self.competition_name,
            "url": self.kaggle_url,
            "task_type": task_type,
            "metric": metadata.get("metric", "unknown"),
            "description": metadata.get("description", ""),
            "data_files": data_info["files"],
            "train_shape": data_info.get("train_shape"),
            "test_shape": data_info.get("test_shape"),
            "target_column": data_info.get("target_column"),
            "feature_columns": data_info.get("feature_columns", []),
            "data_dir": str(self.data_dir),
            "submission_schema": data_info.get("submission_schema")
        }
    
    def _download_data(self):
        """Download competition data using Kaggle API"""
        logger.info("Downloading competition data...")
        
        try:
            # Use kaggle CLI
            import subprocess
            result = subprocess.run(
                ['kaggle', 'competitions', 'download', '-c', self.competition_name, '-p', str(self.data_dir)],
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout
            )
            
            if result.returncode != 0:
                logger.warning(f"Kaggle download warning: {result.stderr}")
            
            # Extract zip files
            for zip_file in self.data_dir.glob("*.zip"):
                logger.info(f"Extracting {zip_file.name}...")
                with zipfile.ZipFile(zip_file, 'r') as zip_ref:
                    zip_ref.extractall(self.data_dir)
                zip_file.unlink()  # Remove zip after extraction
            
            # Log all downloaded files for reference
            data_files = list(self.data_dir.glob("*"))
            logger.info(f"✓ Data downloaded to {self.data_dir}")
            logger.info(f"✓ Downloaded files: {[f.name for f in data_files]}")
            
            # Create a metadata file for future reference
            self._create_data_metadata(data_files)
            
        except subprocess.TimeoutExpired:
            logger.error("Download timeout - competition data too large")
            raise
        except Exception as e:
            logger.error(f"Failed to download data: {e}")
            raise
    
    def _create_data_metadata(self, data_files: List[Path]):
        """Create a metadata file documenting the downloaded data"""
        try:
            metadata_path = self.data_dir / "DATA_INFO.txt"
            
            with open(metadata_path, 'w') as f:
                f.write(f"Competition: {self.competition_name}\n")
                f.write(f"URL: {self.kaggle_url}\n")
                f.write(f"Downloaded: {pd.Timestamp.now()}\n")
                f.write(f"\n{'='*60}\n")
                f.write("DOWNLOADED FILES:\n")
                f.write(f"{'='*60}\n\n")
                
                for data_file in sorted(data_files):
                    if data_file.is_file() and data_file.suffix in ['.csv', '.txt', '.json']:
                        size_mb = data_file.stat().st_size / (1024 * 1024)
                        f.write(f"  {data_file.name}\n")
                        f.write(f"    Size: {size_mb:.2f} MB\n")
                        
                        # Add row count for CSV files
                        if data_file.suffix == '.csv':
                            try:
                                df = pd.read_csv(data_file, nrows=0)
                                # Count rows efficiently
                                with open(data_file) as csv_file:
                                    row_count = sum(1 for _ in csv_file) - 1  # -1 for header
                                f.write(f"    Rows: {row_count:,}\n")
                                f.write(f"    Columns: {len(df.columns)}\n")
                                f.write(f"    Column Names: {', '.join(df.columns)}\n")
                            except Exception as e:
                                f.write(f"    (Could not read CSV: {e})\n")
                        
                        f.write("\n")
                
                f.write(f"\n{'='*60}\n")
                f.write("USAGE:\n")
                f.write(f"{'='*60}\n")
                f.write("This data directory contains all training files used by the agent.\n")
                f.write("Files are preserved for reproducibility and debugging.\n")
                f.write("The generated code references these files directly.\n")
            
            logger.info(f"✓ Created data metadata: {metadata_path}")
            
        except Exception as e:
            logger.warning(f"Could not create data metadata: {e}")
    
    def _analyze_data_files(self) -> Dict[str, Any]:
        """Analyze downloaded data files"""
        files = list(self.data_dir.glob("*.csv"))
        
        info = {
            "files": [f.name for f in files],
        }
        
        # Find train and test files
        train_file = None
        test_file = None
        sample_submission_file = None
        
        for f in files:
            if 'train' in f.name.lower():
                train_file = f
            elif 'test' in f.name.lower():
                test_file = f
            elif 'sample_submission' in f.name.lower() or 'submission' in f.name.lower():
                sample_submission_file = f
        
        # Parse sample_submission.csv as source of truth
        submission_schema = None
        if sample_submission_file:
            submission_schema = self._parse_sample_submission(sample_submission_file, test_file)
            info['submission_schema'] = submission_schema
            logger.info(f"✓ Submission schema: {submission_schema['expected_columns']}")
        
        # Analyze train file
        if train_file:
            try:
                train_df = pd.read_csv(train_file, nrows=1000)  # Sample for speed
                info['train_shape'] = (len(train_df), len(train_df.columns))
                info['feature_columns'] = train_df.columns.tolist()
                
                # Identify target column using submission schema
                target_column = self._identify_target_column(train_df, test_file, submission_schema)
                info['target_column'] = target_column
                
                logger.info(f"✓ Train data: {info['train_shape']}, target: {target_column}")
                
            except Exception as e:
                logger.warning(f"Failed to analyze train file: {e}")
        
        # Analyze test file
        if test_file:
            try:
                test_df = pd.read_csv(test_file, nrows=1000)
                info['test_shape'] = (len(test_df), len(test_df.columns))
                logger.info(f"✓ Test data: {info['test_shape']}")
            except Exception as e:
                logger.warning(f"Failed to analyze test file: {e}")
        
        return info
    
    def _parse_sample_submission(self, sample_submission_file: Path, test_file: Path) -> Dict[str, Any]:
        """
        Parse sample_submission.csv to extract exact submission format requirements.
        This is the source of truth for what the submission should look like.
        """
        try:
            sample_df = pd.read_csv(sample_submission_file)
            
            # First column is almost always the ID column
            id_column = sample_df.columns[0]
            
            # Remaining columns are target columns
            target_columns = sample_df.columns[1:].tolist()
            
            # Infer target type and characteristics for each target column
            target_info = {}
            for col in target_columns:
                unique_vals = sample_df[col].nunique()
                dtype = sample_df[col].dtype
                sample_values = sample_df[col].dropna().values[:10].tolist()
                
                # Determine if binary, multiclass, or regression
                if dtype in ['int64', 'int32'] and unique_vals <= 2:
                    target_type = 'binary'
                elif dtype in ['int64', 'int32'] and unique_vals < 50:
                    target_type = 'multiclass'
                elif dtype in ['float64', 'float32']:
                    target_type = 'regression'
                else:
                    # Default based on unique values
                    target_type = 'multiclass' if unique_vals < 50 else 'regression'
                
                target_info[col] = {
                    'type': target_type,
                    'dtype': str(dtype),
                    'sample_values': sample_values,
                    'unique_count': unique_vals
                }
            
            # Get expected row count from test file
            expected_rows = len(sample_df)
            if test_file:
                try:
                    test_df = pd.read_csv(test_file)
                    expected_rows = len(test_df)
                except:
                    pass
            
            schema = {
                'id_column': id_column,
                'target_columns': target_columns,
                'expected_columns': sample_df.columns.tolist(),
                'target_info': target_info,
                'expected_rows': expected_rows,
                'sample_submission_file': str(sample_submission_file)
            }
            
            logger.info(f"✓ Parsed submission schema: ID={id_column}, Targets={target_columns}")
            return schema
            
        except Exception as e:
            logger.warning(f"Failed to parse sample submission: {e}")
            return None
    
    def _identify_target_column(self, train_df: pd.DataFrame, test_file: Path, 
                                submission_schema: Dict[str, Any]) -> str:
        """
        Identify the target column in train data using multiple strategies.
        Priority: submission_schema > train-test diff > heuristics > last column
        """
        # Strategy 1: Use submission schema (most reliable)
        if submission_schema and submission_schema['target_columns']:
            for target_col in submission_schema['target_columns']:
                if target_col in train_df.columns:
                    logger.info(f"✓ Target identified from submission schema: {target_col}")
                    return target_col
        
        # Strategy 2: Find columns in train but not in test (excluding ID columns)
        if test_file:
            try:
                test_df = pd.read_csv(test_file, nrows=100)
                id_column = submission_schema['id_column'] if submission_schema else None
                
                # Find columns unique to train
                train_only_cols = set(train_df.columns) - set(test_df.columns)
                
                # Remove ID column if present
                if id_column and id_column in train_only_cols:
                    train_only_cols.remove(id_column)
                
                # Also remove common ID patterns
                train_only_cols = {col for col in train_only_cols 
                                  if col.lower() not in ['id', 'index', 'idx']}
                
                if len(train_only_cols) == 1:
                    target_col = list(train_only_cols)[0]
                    logger.info(f"✓ Target identified from train-test diff: {target_col}")
                    return target_col
                elif len(train_only_cols) > 1:
                    # Multiple candidates - use heuristics
                    logger.warning(f"Multiple target candidates: {train_only_cols}")
                    
            except Exception as e:
                logger.warning(f"Could not compare train/test: {e}")
        
        # Strategy 3: Use common naming patterns
        target_keywords = ['target', 'label', 'survived', 'outcome', 'class', 'y']
        potential_targets = [col for col in train_df.columns if 
                           any(keyword in col.lower() for keyword in target_keywords)]
        
        if potential_targets:
            target_col = potential_targets[0]
            logger.info(f"✓ Target identified from naming pattern: {target_col}")
            return target_col
        
        # Strategy 4: Last resort - use last column
        target_col = train_df.columns[-1]
        logger.warning(f"⚠ Using last column as target (fallback): {target_col}")
        return target_col
    
    def _scrape_competition_page(self) -> Dict[str, str]:
        """
        Enhanced competition page scraping for deeper understanding
        """
        metadata = {}
        
        try:
            response = requests.get(self.kaggle_url, timeout=10)
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract full page text for analysis
            page_text = soup.get_text().lower()
            
            # 1. Identify evaluation metric (more comprehensive)
            metric_patterns = {
                'accuracy': ['accuracy', 'correct predictions'],
                'auc': ['auc', 'area under curve', 'roc auc'],
                'f1': ['f1', 'f1-score', 'f1 score'],
                'rmse': ['rmse', 'root mean squared error'],
                'mae': ['mae', 'mean absolute error'],
                'mse': ['mse', 'mean squared error'],
                'logloss': ['logloss', 'log loss', 'logarithmic loss'],
                'r2': ['r2', 'r-squared', 'r squared'],
                'precision': ['precision'],
                'recall': ['recall'],
            }
            
            for metric_name, patterns in metric_patterns.items():
                if any(pattern in page_text for pattern in patterns):
                    metadata['metric'] = metric_name
                    logger.info(f"✓ Detected metric: {metric_name}")
                    break
            
            # 2. Extract competition description/overview
            # Look for specific sections
            overview_sections = soup.find_all(['div', 'section'], class_=lambda c: c and ('overview' in c.lower() or 'description' in c.lower()))
            if overview_sections:
                description = overview_sections[0].get_text().strip()[:1000]
                metadata['description'] = description
            else:
                # Fallback to paragraphs
                paragraphs = soup.find_all('p')
                if paragraphs:
                    # Combine first few paragraphs for better context
                    description = ' '.join([p.get_text().strip() for p in paragraphs[:3]])[:1000]
                    metadata['description'] = description
            
            # 3. Identify task-specific keywords
            task_indicators = {
                'survival': ['survive', 'survival', 'died', 'death'],
                'price_prediction': ['price', 'cost', 'value', 'sales'],
                'classification': ['classify', 'classification', 'category', 'class'],
                'regression': ['predict', 'estimate', 'forecast'],
                'time_series': ['time series', 'temporal', 'sequential'],
                'image': ['image', 'vision', 'picture', 'photo'],
                'nlp': ['text', 'nlp', 'sentiment', 'language'],
            }
            
            detected_tasks = []
            for task, keywords in task_indicators.items():
                if any(kw in page_text for kw in keywords):
                    detected_tasks.append(task)
            
            if detected_tasks:
                metadata['task_indicators'] = detected_tasks
                logger.info(f"✓ Task indicators: {detected_tasks}")
            
            # 4. Extract key requirements
            if 'binary' in page_text or 'two class' in page_text:
                metadata['num_classes'] = 2
            elif 'multiclass' in page_text or 'multi-class' in page_text:
                # Try to find number of classes
                import re
                class_match = re.search(r'(\d+)\s+class', page_text)
                if class_match:
                    metadata['num_classes'] = int(class_match.group(1))
            
            logger.info(f"✓ Scraped competition metadata: {len(metadata)} fields")
            return metadata
            
        except Exception as e:
            logger.warning(f"Failed to scrape competition page: {e}")
            return metadata
    
    def _determine_task_type(self, data_info: Dict, metadata: Dict) -> str:
        """Determine if classification or regression"""
        # Try to infer from metric
        metric = metadata.get('metric', '').lower()
        if any(m in metric for m in ['accuracy', 'auc', 'f1', 'logloss']):
            return 'classification'
        if any(m in metric for m in ['rmse', 'mae', 'mse']):
            return 'regression'
        
        # Try to infer from target column
        train_file = self.data_dir / 'train.csv'
        if train_file.exists() and data_info.get('target_column'):
            try:
                df = pd.read_csv(train_file, nrows=1000)
                target = data_info['target_column']
                unique_vals = df[target].nunique()
                
                # If few unique values, likely classification
                if unique_vals < 20:
                    return 'classification'
                else:
                    return 'regression'
            except:
                pass
        
        # Default to classification (more common on Kaggle)
        return 'classification'

