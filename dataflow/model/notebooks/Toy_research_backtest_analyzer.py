# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.15.2
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Description

# %% [markdown]
# Explore research backtest results.
#
# **Note**: use `dataflow/model/notebooks/Master_backtest_analysis_param_sweep.ipynb` for standard backtest analysis.
# This notebook is used for free-form analysis and hypotheses testing, and thus is not as strictly maintained.
# %% [markdown]
# # Imports

# %%
# %load_ext autoreload
# %autoreload 2
# %matplotlib inline

# %%
import datetime
import logging
import os

import pandas as pd

import core.config as cconfig
import core.plotting as coplotti
import dataflow.model as dtfmod
import helpers.hdbg as hdbg
import helpers.henv as henv
import helpers.hgit as hgit
import helpers.hparquet as hparque
import helpers.hprint as hprint
import oms.broker.ccxt.ccxt_utils as obccccut

# %%
hdbg.init_logger(verbosity=logging.INFO)

_LOG = logging.getLogger(__name__)

_LOG.info("%s", henv.get_system_signature()[0])

hprint.config_notebook()


# %% [markdown]
# # Build the config dict

# %%
# Get config from env when running the notebook via the `run_notebook.py` script.
default_config = cconfig.get_config_from_env()
if default_config:
    _LOG.info("Using config from env vars")
else:
    _LOG.info("Using hardwired config")
    # Build default config.
    amp_dir = hgit.get_amp_abs_path()
    dir_name = os.path.join(
        amp_dir,
        "/shared_data/backtest.danya/build_tile_configs.C11a.ccxt_v8_1-all.6T.2023-06-01_2024-01-31.ins.run0/tiled_results",
    )
    # Create a subfolder to store portfolio metrics.
    # The subfolder is marked by the datetime of the run, e.g.
    # "build_tile_configs.C11a.ccxt_v8_1-all.5T.2023-01-01_2024-03-20.ins.run0/portfolio_dfs/20240326_131724".
    # TODO(Danya): Factor out into a function.
    output_dir_name = os.path.join(
        dir_name.rstrip("tiled_results"),
        "portfolio_dfs",
        pd.Timestamp.utcnow().strftime("%Y%m%d_%H%M%S"),
    )
    default_config_dict = {
        "dir_name": dir_name,
        "output_dir_name": output_dir_name,
        "start_date": datetime.date(2024, 1, 1),
        "end_date": datetime.date(2024, 1, 31),
        "asset_id_col": "asset_id",
        "pnl_resampling_frequency": "D",
        "rule": "6T",
        "im_client_config": {
            "vendor": "ccxt",
            "universe_version": "v8.1",
            "root_dir": "s3://cryptokaizen-data.preprod/v3",
            "partition_mode": "by_year_month",
            "dataset": "ohlcv",
            "contract_type": "futures",
            "data_snapshot": "",
            "aws_profile": "ck",
            "version": "v1_0_0",
            "download_universe_version": "v8",
            "tag": "downloaded_1min",
            "download_mode": "periodic_daily",
            "downloading_entity": "airflow",
            "resample_1min": False,
        },
        "annotate_forecasts_kwargs": {
            "style": "longitudinal",
            "quantization": 30,
            "liquidate_at_end_of_day": False,
            "initialize_beginning_of_day_trades_to_zero": False,
            "burn_in_bars": 3,
            "compute_extended_stats": True,
            "target_dollar_risk_per_name": 1.0,
            "modulate_using_prediction_magnitude": False,
            "prediction_abs_threshold": 0.3,
        },
        "column_names": {
            "price_col": "open",
            "volatility_col": "garman_klass_vol",
            "prediction_col": "feature",
        },
        "bin_annotated_portfolio_df_kwargs": {
            "proportion_of_data_per_bin": 0.2,
            "normalize_prediction_col_values": False,
        },
        "load_all_tiles_in_memory": True,
        "sweep_param": {
            "keys": (
                "column_names",
                "price_col",
            ),
            "values": [
                "open",
            ],
        },
    }
    # Add asset_id_to_share_decimals based on the `quantization` parameter.
    if not default_config_dict["annotate_forecasts_kwargs"]["quantization"]:
        asset_id_to_share_decimals = obccccut.get_asset_id_to_share_decimals(
            "amount_precision"
        )
        default_config_dict["annotate_forecasts_kwargs"][
            "asset_id_to_share_decimals"
        ] = asset_id_to_share_decimals
    else:
        default_config_dict["annotate_forecasts_kwargs"][
            "asset_id_to_share_decimals"
        ] = None
    # Build config from dict.
    default_config = cconfig.Config().from_dict(default_config_dict)
print(default_config)

# %% [markdown]
# # Load tiled results

# %% [markdown]
# ## Report tile stats

# %%
parquet_tile_analyzer = dtfmod.ParquetTileAnalyzer()
parquet_tile_metadata = parquet_tile_analyzer.collate_parquet_tile_metadata(
    default_config["dir_name"]
)

# %%
parquet_tile_analyzer.compute_metadata_stats_by_asset_id(parquet_tile_metadata)

# %%
parquet_tile_analyzer.compute_universe_size_by_time(parquet_tile_metadata)

# %%
asset_ids = parquet_tile_metadata.index.levels[0].to_list()
display(asset_ids)

# %% [markdown]
# ## Load tile data

# %%
if default_config["load_all_tiles_in_memory"]:
    asset_ids_to_load = asset_ids
else:
    asset_ids_to_load = asset_ids[0:1]
asset_batch_size = len(asset_ids_to_load)
cols = None
#
asset_tile = next(
    hparque.yield_parquet_tiles_by_assets(
        default_config["dir_name"],
        asset_ids_to_load,
        default_config["asset_id_col"],
        asset_batch_size,
        cols,
    )
)

# %%
tile_df = dtfmod.process_parquet_read_df(
    asset_tile, default_config["asset_id_col"]
)

# %%
tile_df.columns.levels[0].to_list()

# %%
tile_df.head(3)

# %% [markdown]
# # Compute and save portfolio bar metrics

# %%
# Get configs sweeping over parameter.
config_dict = dtfmod.build_research_backtest_analyzer_config_sweep(default_config)
print(config_dict.keys())

# %%
portfolio_df_dict = {}
bar_metrics_dict = {}
for key, config in config_dict.items():
    if config["load_all_tiles_in_memory"]:
        fep = dtfmod.ForecastEvaluatorFromPrices(
            **config["column_names"].to_dict(),
        )
        # Create a subdirectory for the current config, e.g.
        # "optimizer_config_dict:constant_correlation_penalty=1".
        experiment_dir = os.path.join(
            config["output_dir_name"], key.replace(" ", "")
        )
        _LOG.info("Saving portfolio in experiment_dir=%s", experiment_dir)
        file_name = fep.save_portfolio(
            tile_df,
            experiment_dir,
            **config["annotate_forecasts_kwargs"].to_dict(),
        )
        # Load back the portfolio and metrics that were calculated.
        portfolio_df, bar_metrics = fep.load_portfolio_and_stats(
            experiment_dir, file_name=file_name
        )
    else:
        portfolio_df, bar_metrics = dtfmod.annotate_forecasts_by_tile(
            config["dir_name"],
            config["start_date"],
            config["end_date"],
            config["asset_id_col"],
            config["column_names"]["price_col"],
            config["column_names"]["volatility_col"],
            config["column_names"]["prediction_col"],
            asset_ids=None,
            annotate_forecasts_kwargs=config[
                "annotate_forecasts_kwargs"
            ].to_dict(),
            return_portfolio_df=True,
        )
    portfolio_df_dict[key] = portfolio_df
    bar_metrics_dict[key] = bar_metrics
portfolio_stats_df = pd.concat(bar_metrics_dict, axis=1)


# %%
coplotti.plot_portfolio_stats(
    portfolio_stats_df, freq=default_config["pnl_resampling_frequency"]
)

# %%
coplotti.plot_portfolio_binned_stats(
    portfolio_df_dict,
    **config["bin_annotated_portfolio_df_kwargs"],
)

# %% [markdown]
# # Compute aggregate portfolio stats

# %%
stats_computer = dtfmod.StatsComputer()

# %%
portfolio_stats, daily_metrics = stats_computer.compute_portfolio_stats(
    portfolio_stats_df,
    default_config["pnl_resampling_frequency"],
)
display(portfolio_stats)

# %%
