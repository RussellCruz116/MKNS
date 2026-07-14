import os
import json
import pandas as pd
import numpy as np
import geopandas as gpd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score
import joblib

def train_s3_extrapolator(geojson_path, output_model_path="s3_rf_model.pkl"):
    print(f"Loading data from {geojson_path}...")
    try:
        gdf = gpd.read_file(geojson_path)
    except Exception as e:
        print(f"Error loading GeoJSON: {e}")
        return

    # Extract relevant features
    # Features (X): LandUse, RoadClass, SpeedLimit, F85thPercentileSpeed, RankedPercentile
    # Target (y): Multi-output including 6 category scores and the final SpeedSafetyScore
    
    features = ['LandUse', 'RoadClass', 'SpeedLimit', 'F85thPercentileSpeed', 'RankedPercentile']
    targets = [
        'Score_Kinematics', 'Score_Friction', 'Score_VRU',
        'Score_Speeding', 'Score_AI', 'Score_Stress',
        'Score_Infrastructure', 'SpeedSafetyScore'
    ]
    
    df = pd.DataFrame(gdf.drop(columns='geometry'))
    # Ensure RankedPercentile is numeric before dropping NAs
    df['RankedPercentile'] = pd.to_numeric(df['RankedPercentile'], errors='coerce').fillna(0.5)
    
    # Ensure all targets are numeric
    for t in targets:
        df[t] = pd.to_numeric(df[t], errors='coerce').fillna(0.0)
        
    df = df[features + targets].dropna()
    
    if len(df) == 0:
        print("No valid data for training after dropping NAs.")
        return
        
    print(f"Training on {len(df)} road segments.")
    
    # One-hot encode categorical variables
    X = pd.get_dummies(df[features], columns=['LandUse', 'RoadClass'], drop_first=True)
    y = df[targets]
    
    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # Initialize and train RandomForest
    print("Training RandomForestRegressor...")
    model = RandomForestRegressor(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
    model.fit(X_train, y_train)
    
    # Evaluate
    y_pred = model.predict(X_test)
    mse = mean_squared_error(y_test, y_pred, multioutput='uniform_average')
    r2 = r2_score(y_test, y_pred, multioutput='uniform_average')
    
    print(f"Model Evaluation (Average) -> MSE: {mse:.2f}, R2 Score: {r2:.2f}")
    
    # Save model
    joblib.dump(model, output_model_path)
    
    # Also save the columns so we can align during inference
    model_meta = {
        'columns': list(X.columns),
        'r2_score': r2
    }
    with open(output_model_path.replace('.pkl', '_meta.json'), 'w') as f:
        json.dump(model_meta, f)
        
    print(f"Model saved to {output_model_path}")
    
    # Feature Importances
    importances = pd.DataFrame({
        'Feature': X.columns,
        'Importance': model.feature_importances_
    }).sort_values('Importance', ascending=False)
    
    print("\nFeature Importances:")
    print(importances.to_string(index=False))

def align_rubric_categories(df, score_col='SpeedSafetyScore'):
    categories = {
        'Score_Kinematics': 'Max_Kinematics',
        'Score_Friction': 'Max_Friction',
        'Score_VRU': 'Max_VRU',
        'Score_Speeding': 'Max_Speeding',
        'Score_AI': 'Max_AI',
        'Score_Stress': 'Max_Stress',
        'Score_Infrastructure': 'Max_Infrastructure'
    }
    
    # Calculate current sum
    raw_sum = sum(df[cat] for cat in categories.keys())
    raw_sum_is_zero = (raw_sum == 0)
    
    if raw_sum_is_zero.any():
        for cat, max_col in categories.items():
            df.loc[raw_sum_is_zero, cat] = df.loc[raw_sum_is_zero, max_col] * 0.1
        raw_sum = sum(df[cat] for cat in categories.keys())
        
    final_score = df[score_col]
    
    under_score = final_score > raw_sum
    over_score = final_score < raw_sum
    
    # Case 1: final_score < raw_sum (over-estimate)
    factor = np.where(raw_sum > 0, final_score / raw_sum, 0.0)
    for cat in categories.keys():
        df.loc[over_score, cat] = df.loc[over_score, cat] * factor[over_score]
        
    # Case 2: final_score > raw_sum (under-estimate)
    total_room = sum(df[max_col] - df[cat] for cat, max_col in categories.items())
    total_room = np.where(total_room > 0, total_room, 1.0)
    
    for cat, max_col in categories.items():
        room = df[max_col] - df[cat]
        df.loc[under_score, cat] = df.loc[under_score, cat] + (final_score[under_score] - raw_sum[under_score]) * (room[under_score] / total_room[under_score])
        
    # Finally, clip to limits row-by-row
    for cat, max_col in categories.items():
        df[cat] = np.clip(df[cat], 0.0, df[max_col])
        
    return df

def run_whatif_scenario(geojson_path, model_path, output_geojson):
    print(f"Loading data for What-If scenario...")
    try:
        gdf = gpd.read_file(geojson_path)
    except Exception as e:
        print(f"Error loading GeoJSON: {e}")
        return

    model = joblib.load(model_path)
    with open(model_path.replace('.pkl', '_meta.json'), 'r') as f:
        model_meta = json.load(f)
    model_cols = model_meta['columns']

    # Phase 35/37: Specific AI Interventions & Budget Mapping
    # Instead of blanket urban/rural limits, the ML simulates the explicit actions suggested by the AI Evaluators
    # and maps them to real-world costs.
    print("Applying What-If Interventions based on explicit AI Board recommendations and mapping budgets...")
    
    # Defaults
    gdf['OriginalSpeedLimit'] = gdf['SpeedLimit']
    gdf['OriginalS3'] = gdf['SpeedSafetyScore']
    gdf['AI_SpeedIntervention'] = gdf['AI_SpeedIntervention'].fillna('')

    # Iterate and apply dynamic physics modifiers and costs based on AI text
    def apply_ai_physics(row):
        interv = str(row['AI_SpeedIntervention']).lower()
        limit = row['SpeedLimit']
        f85 = row['F85thPercentileSpeed']
        details = []
        cost = 0.0
        
        # Smart speedway/long road logic: align limit to design speed and segregate lanes
        if 'align' in interv or ('segregate' in interv and (row['RoadClass'] == 'motorway' or row['SpeedLimit'] >= 60)):
            limit = max(row['SpeedLimit'], min(100.0, row['F85thPercentileSpeed']))
            f85 = limit
            details.append("Align Limit & Segregate")
            cost += 55000.0
        else:
            if 'automated enforcement' in interv or 'cameras' in interv:
                f85 = min(f85, limit)
                details.append("Automated Enforcement")
                cost += 15000.0
            if 'traffic calming' in interv or 'chicanes' in interv or 'bumps' in interv:
                f85 = f85 * 0.80
                details.append("Traffic Calming")
                cost += 25000.0
            if 'segregate' in interv:
                f85 = f85 * 0.90
                details.append("VRU Segregation")
                cost += 50000.0
            if 'reduce limits' in interv:
                limit = limit - 10.0
                f85 = f85 * 0.90
                details.append("Reduce Speed Limits")
                cost += 5000.0
            
        action_text = " | ".join(details) if details else "None"
        return pd.Series({'SpeedLimit': limit, 'F85thPercentileSpeed': f85, 'WhatIf_Action_Details': action_text, 'Intervention_Cost': cost})

    new_physics = gdf.apply(apply_ai_physics, axis=1)
    gdf['SpeedLimit'] = new_physics['SpeedLimit']
    gdf['F85thPercentileSpeed'] = new_physics['F85thPercentileSpeed']
    gdf['WhatIf_Action_Details'] = new_physics['WhatIf_Action_Details']
    gdf['Intervention_Cost'] = new_physics['Intervention_Cost']

    # Prepare features
    features = ['LandUse', 'RoadClass', 'SpeedLimit', 'F85thPercentileSpeed', 'RankedPercentile']
    df_inf = pd.DataFrame(gdf.drop(columns='geometry'))
    df_inf['RankedPercentile'] = pd.to_numeric(df_inf['RankedPercentile'], errors='coerce').fillna(0.5)
    X_inf = pd.get_dummies(df_inf[features], columns=['LandUse', 'RoadClass'])

    # Align columns with training data
    for col in model_cols:
        if col not in X_inf.columns:
            X_inf[col] = 0
    X_inf = X_inf[model_cols]

    # Predict
    print("Predicting new S3 Scores and Category Sub-Scores...")
    X_inf = X_inf.fillna(0)
    preds = model.predict(X_inf)
    
    # Map predictions back to the GDF and clip to their theoretical limits
    targets = [
        'Score_Kinematics', 'Score_Friction', 'Score_VRU',
        'Score_Speeding', 'Score_AI', 'Score_Stress',
        'Score_Infrastructure', 'SpeedSafetyScore'
    ]
    for i, target_col in enumerate(targets):
        if target_col == 'SpeedSafetyScore':
            gdf[target_col] = np.clip(preds[:, i], 0.0, 100.0)
        else:
            max_col = 'Max_' + target_col.split('_')[1]
            gdf[target_col] = np.clip(preds[:, i], 0.0, gdf[max_col])
            
    # Apply monotonicity constraint: What-If safety score cannot drop below the baseline score
    gdf['SpeedSafetyScore'] = np.maximum(gdf['SpeedSafetyScore'], gdf['OriginalS3'])
    
    # Align rubric category sub-scores to sum exactly to the final score
    gdf = align_rubric_categories(gdf)
            
    gdf['S3_Improvement'] = gdf['SpeedSafetyScore'] - gdf['OriginalS3']
    gdf['Safety_ROI'] = np.where(gdf['Intervention_Cost'] > 0, (gdf['S3_Improvement'] / (gdf['Intervention_Cost'] / 10000.0)), 0.0)

    print(f"Exporting What-If GeoJSON to {output_geojson}...")
    gdf.to_file(output_geojson, driver='GeoJSON')
    print("Done!")

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    geojson_path = os.path.join(base_dir, 'outputs', 'data', 'makenes_scored.geojson')
    out_model = os.path.join(base_dir, 'models', 's3_rf_model.pkl')
    out_whatif = os.path.join(base_dir, 'outputs', 'data', 'makenes_whatif_scored.geojson')
    
    os.makedirs(os.path.dirname(out_model), exist_ok=True)
    train_s3_extrapolator(geojson_path, out_model)
    run_whatif_scenario(geojson_path, out_model, out_whatif)
