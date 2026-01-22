import rasterio
import numpy as np

# 1. Open the Near-Infrared (NIR) and Red bands
with rasterio.open('nir.tiff') as src_nir:
    nir = src_nir.read(1)
    meta = src_nir.meta  # Copy metadata (coords, size, projection)

with rasterio.open('red.tiff') as src_red:
    red = src_red.read(1)

# 2. Allow division by zero (handle empty pixels gracefully)
np.seterr(divide='ignore', invalid='ignore')

# 3. Calculate NDVI Formula: (NIR - Red) / (NIR + Red)
# Result is between -1 (Water/Concrete) and +1 (Dense Forest)
ndvi = (nir - red) / (nir + red)

# 4. Clean the data (Clamp values to -1 and 1)
ndvi = np.nan_to_num(ndvi, nan=-1.0) # Replace errors with "concrete" score
ndvi = np.clip(ndvi, -1.0, 1.0)

# 5. Update metadata for the new file
meta.update(dtype=rasterio.float32, count=1)

# 6. Save the NDVI map
with rasterio.open('ndvi_final.tiff', 'w', **meta) as dst:
    dst.write(ndvi.astype(rasterio.float32), 1)

print("✅ Success: 'ndvi_final.tiff' created.")