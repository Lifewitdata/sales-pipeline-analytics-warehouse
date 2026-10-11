with products as (

    select * from {{ ref('stg_crm_products') }}

)

select
    product_key,
    product_name,
    product_name_normalized,
    product_series,
    list_price
from products
