with source as (

    select * from {{ source('crm_raw', 'products') }}

),

cleaned as (

    select
        trim(product)                                        as product_name,

        {#- DQ-003: the opportunity source carries the malformed label 'GTXPro'
            where this master has 'GTX Pro' on 1,480 rows. The raw label is
            never edited - a lowercase alphanumeric-normalised key lets the
            intermediate layer join the two spellings back together, and the
            repair is auditable on every row. -#}
        lower(regexp_replace(trim(product), '[^A-Za-z0-9]', '', 'g'))
                                                             as product_name_normalized,
        trim(product) in ('GTXPro', 'GTX Pro')               as is_gtx_pro_variant,

        trim(series)                                         as product_series,
        sales_price                                          as list_price,

        _loaded_at

    from source

)

select
    {{ surrogate_key(['product_name']) }}                    as product_key,
    product_name,
    product_name_normalized,
    is_gtx_pro_variant,
    product_series,
    list_price,
    _loaded_at
from cleaned
